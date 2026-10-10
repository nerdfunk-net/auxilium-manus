"""Per-user AI assistant settings: master switch, provider/model, write-only API key.

See doc/ai_integration/AI_ASSISTANT.md §3.2. The API key is encrypted at rest, never
returned by any read path, and only decrypted through ``resolve_api_key``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from core.crypto import EncryptionService
from models.ai_assistant import (
    AiModelOption,
    AiProvider,
    AiStatusResponse,
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
)
from repositories.user_ai_settings_repository import UserAiSettingsRepository
from services.ai_assistant.base_url_policy import BaseUrlPolicyError, validate_llm_base_url
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)

# Providers with a working adapter.
ENABLED_PROVIDERS: tuple[AiProvider, ...] = ("anthropic", "gemini", "openai_compat")

# Providers whose model is free text (a local server serves whatever the operator pulled).
FREE_TEXT_MODEL_PROVIDERS: frozenset[str] = frozenset({"openai_compat"})
# Providers where the API key is optional (a local model server typically has none).
KEY_OPTIONAL_PROVIDERS: frozenset[str] = frozenset({"openai_compat"})

DEFAULT_PROVIDER: AiProvider = "anthropic"

# Selectable models per provider. This is a UI/validation list only: nothing downstream
# branches on a model id (providers are treated equally, see AI_ASSISTANT.md §3.1). The first
# entry of each list is that provider's default.
PROVIDER_MODELS: dict[str, tuple[AiModelOption, ...]] = {
    "anthropic": (
        AiModelOption(
            id="claude-haiku-5-5",
            label="Claude Haiku 5.5 (default)",
            description=(
                "Fast and low cost. Good for editing Jinja2 templates and simple questions."
            ),
        ),
        AiModelOption(
            id="claude-sonnet-5-5",
            label="Claude Sonnet 5.5",
            description="Stronger reasoning for complex workflows. Costs more than Haiku.",
        ),
    ),
    # Which of these your Google AI Studio plan can use varies (the free tier is limited).
    "gemini": (
        AiModelOption(
            id="gemini-3.8-flash",
            label="Gemini 3.8 Flash (default)",
            description="Fast, general purpose. Good for editing Jinja2 templates.",
        ),
        AiModelOption(
            id="gemini-3.5-flash-lite",
            label="Gemini 3.5 Flash-Lite",
            description="Lowest cost; best for simple edits and questions.",
        ),
        AiModelOption(
            id="gemini-3.1-pro-preview",
            label="Gemini 3.1 Pro (preview)",
            description="Stronger reasoning for complex workflows. Preview models can change.",
        ),
    ),
}
DEFAULT_MODELS: dict[str, str] = {
    provider: options[0].id for provider, options in PROVIDER_MODELS.items()
}


def _effective_model(provider: str, stored: str | None) -> str:
    """The stored model if it is still offered, else the provider default."""
    if provider in FREE_TEXT_MODEL_PROVIDERS:
        return stored or ""
    allowed = {option.id for option in PROVIDER_MODELS.get(provider, ())}
    if stored and stored in allowed:
        return stored
    return DEFAULT_MODELS.get(provider, "")


def _key_map(row: Any) -> dict[str, str]:
    """Provider -> Fernet token. The column holds JSON of individually encrypted keys, so
    presence checks never decrypt."""
    blob = row.api_key_encrypted if row is not None else None
    if blob is None:
        return {}
    try:
        data = json.loads(bytes(blob))  # the driver may hand back a memoryview
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {provider: token for provider, token in data.items() if isinstance(token, str)}


def _has_key(row: Any) -> bool:
    return row is not None and row.provider in _key_map(row)


def _is_configured(row: Any) -> bool:
    """A key for hosted providers; a base URL and model for an OpenAI-compatible server."""
    if row.provider in KEY_OPTIONAL_PROVIDERS:
        return bool(row.base_url and row.model)
    return _has_key(row)


def _not_configured_message(provider: str) -> str:
    if provider in KEY_OPTIONAL_PROVIDERS:
        return "A base URL and a model are required"
    return "No API key is configured"


def _available_models() -> dict[str, list[AiModelOption]]:
    return {
        provider: list(options)
        for provider, options in PROVIDER_MODELS.items()
        if provider in ENABLED_PROVIDERS
    }


class _SettingsRepository(Protocol):
    def get_by_user_id(self, user_id: int) -> Any | None: ...

    def upsert(self, user_id: int, values: dict[str, Any]) -> Any: ...


SHARE_FLAGS = (
    "share_inventory_data",
    "share_device_addresses",
    "share_custom_fields",
    "share_config_context",
    "share_content_data",
)


@dataclass(frozen=True)
class AiRuntimeConfig:
    """Everything the chat path needs. ``api_key`` is excluded from ``repr``."""

    provider: str
    model: str
    base_url: str | None
    api_key: str = field(repr=False)
    share_inventory_data: bool
    share_content_data: bool
    share_device_addresses: bool = False
    share_custom_fields: bool = False
    share_config_context: bool = False

    @property
    def sharing(self) -> SharingPolicy:
        return SharingPolicy(
            inventory=self.share_inventory_data,
            addresses=self.share_device_addresses,
            custom_fields=self.share_custom_fields,
            config_context=self.share_config_context,
            content=self.share_content_data,
        )


class AiSettingsService:
    def __init__(
        self, repo: _SettingsRepository, encryption: EncryptionService | None = None
    ) -> None:
        self._repo = repo
        self._encryption = encryption

    @classmethod
    def from_session(cls, db: Session) -> AiSettingsService:
        """Production constructor: routers hold a session, never a repository."""
        return cls(UserAiSettingsRepository(db))

    # -- reads ---------------------------------------------------------------

    def get(self, user_id: int) -> UserAiSettingsResponse:
        row = self._repo.get_by_user_id(user_id)
        if row is None:
            return UserAiSettingsResponse(
                enabled=False,
                provider=DEFAULT_PROVIDER,
                model=DEFAULT_MODELS[DEFAULT_PROVIDER],
                base_url=None,
                api_key_set=False,
                configured=False,
                share_inventory_data=False,
                share_device_addresses=False,
                share_custom_fields=False,
                share_config_context=False,
                share_content_data=False,
                available_providers=list(ENABLED_PROVIDERS),
                available_models=_available_models(),
            )
        return UserAiSettingsResponse(
            enabled=bool(row.enabled),
            provider=row.provider,
            model=_effective_model(row.provider, row.model),
            base_url=row.base_url,
            api_key_set=_has_key(row),
            configured=_is_configured(row),
            share_inventory_data=bool(row.share_inventory_data),
            share_device_addresses=bool(row.share_device_addresses),
            share_custom_fields=bool(row.share_custom_fields),
            share_config_context=bool(row.share_config_context),
            share_content_data=bool(row.share_content_data),
            available_providers=list(ENABLED_PROVIDERS),
            available_models=_available_models(),
        )

    def status(self, user_id: int, *, has_permission: bool) -> AiStatusResponse:
        """Availability = permission AND master switch AND a usable provider configuration."""
        if not has_permission:
            return AiStatusResponse(available=False, reason="no_permission")
        row = self._repo.get_by_user_id(user_id)
        if row is None or not row.enabled:
            return AiStatusResponse(available=False, reason="disabled")
        if not _is_configured(row):
            return AiStatusResponse(available=False, reason="not_configured")
        return AiStatusResponse(available=True, reason="ok")

    def resolve_api_key(self, user_id: int) -> str | None:
        """Decrypt the owner's key. The only read path that returns cleartext."""
        row = self._repo.get_by_user_id(user_id)
        token = _key_map(row).get(row.provider) if row is not None else None
        if token is None:
            return None
        try:
            cleartext = self._enc().decrypt(token.encode("ascii"))
        except ValueError as exc:
            # The credential encryption secret was rotated since the key was saved.
            raise AiAssistantNotConfiguredError(
                "The stored API key can no longer be decrypted; please enter it again"
            ) from exc
        return cleartext

    def require_runtime_config(
        self, user_id: int, *, require_enabled: bool = True
    ) -> AiRuntimeConfig:
        """Server-side gate for every assistant endpoint that talks to a provider.

        ``require_enabled=False`` exists only for the connection test, so a user can verify
        a configuration before switching the assistant on.
        """
        row = self._repo.get_by_user_id(user_id)
        if row is None:
            if require_enabled:
                raise AiAssistantDisabledError("The AI assistant is disabled for this user")
            raise AiAssistantNotConfiguredError("The AI assistant is not configured")
        if require_enabled and not row.enabled:
            raise AiAssistantDisabledError("The AI assistant is disabled for this user")
        if not _is_configured(row):
            raise AiAssistantNotConfiguredError(_not_configured_message(row.provider))
        return AiRuntimeConfig(
            provider=row.provider,
            model=_effective_model(row.provider, row.model),
            base_url=row.base_url,
            api_key=self.resolve_api_key(user_id) or "",
            share_inventory_data=bool(row.share_inventory_data),
            share_device_addresses=bool(row.share_device_addresses),
            share_custom_fields=bool(row.share_custom_fields),
            share_config_context=bool(row.share_config_context),
            share_content_data=bool(row.share_content_data),
        )

    # -- writes --------------------------------------------------------------

    def update(self, user_id: int, data: UserAiSettingsUpdate) -> UserAiSettingsResponse:
        if data.api_key is not None and data.clear_api_key:
            raise AiSettingsValidationError("Provide either api_key or clear_api_key, not both")
        if data.provider is not None and data.provider not in ENABLED_PROVIDERS:
            raise AiSettingsValidationError(f"Provider {data.provider!r} is not available")

        existing = self._repo.get_by_user_id(user_id)
        provider = data.provider or (
            existing.provider if existing is not None else DEFAULT_PROVIDER
        )
        provider_changed = existing is None or existing.provider != provider
        values: dict[str, Any] = {}

        self._apply_model(values, data, provider, provider_changed)
        self._apply_base_url(values, data, provider, existing, provider_changed)

        if data.enabled is not None:
            values["enabled"] = data.enabled
        if data.provider is not None:
            values["provider"] = data.provider
        for flag in SHARE_FLAGS:
            if getattr(data, flag) is not None:
                values[flag] = getattr(data, flag)
        if data.api_key is not None or data.clear_api_key:
            keys = _key_map(existing)
            if data.api_key is not None:
                token = self._enc().encrypt(data.api_key.get_secret_value())
                keys = {**keys, provider: token.decode("ascii")}
            else:
                keys = {k: v for k, v in keys.items() if k != provider}
            values["api_key_encrypted"] = json.dumps(keys).encode("ascii") if keys else None

        if values:
            self._repo.upsert(user_id, values)
        return self.get(user_id)

    @staticmethod
    def _apply_model(
        values: dict[str, Any], data: UserAiSettingsUpdate, provider: str, provider_changed: bool
    ) -> None:
        if data.model is not None:
            if provider not in FREE_TEXT_MODEL_PROVIDERS and data.model not in {
                option.id for option in PROVIDER_MODELS.get(provider, ())
            }:
                raise AiSettingsValidationError(
                    f"Model {data.model!r} is not available for provider {provider!r}"
                )
            values["model"] = data.model
        elif provider_changed:
            # A model id from another provider is meaningless here; start from this one's default.
            values["model"] = DEFAULT_MODELS.get(provider, "")

    def _apply_base_url(
        self,
        values: dict[str, Any],
        data: UserAiSettingsUpdate,
        provider: str,
        existing: Any | None,
        provider_changed: bool,
    ) -> None:
        if provider != "openai_compat":
            if data.base_url:
                raise AiSettingsValidationError(
                    "A base URL is only used by the OpenAI-compatible provider"
                )
            if existing is not None and existing.base_url is not None:
                values["base_url"] = None
            return
        if data.base_url is None:
            if provider_changed:
                values["base_url"] = None
            return
        if data.base_url.strip() == "":
            values["base_url"] = None
            return
        has_key = data.api_key is not None or (
            existing is not None and provider in _key_map(existing) and not data.clear_api_key
        )
        try:
            values["base_url"] = validate_llm_base_url(data.base_url.strip(), has_api_key=has_key)
        except BaseUrlPolicyError as exc:
            raise AiSettingsValidationError(str(exc)) from exc

    def _enc(self) -> EncryptionService:
        if self._encryption is None:
            self._encryption = EncryptionService()
        return self._encryption
