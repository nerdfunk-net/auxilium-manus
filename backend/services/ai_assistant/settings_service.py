"""Per-user AI assistant settings: master switch, provider/model, write-only API key.

See doc/ai_integration/AI_ASSISTANT.md §3.2. The API key is encrypted at rest, never
returned by any read path, and only decrypted through ``resolve_api_key`` so the cleartext
is registered for run-scoped redaction.
"""

from __future__ import annotations

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
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.workflow_context.secret_fields import register_secret_value

# Providers with a working adapter. Gemini and openai_compat are phase 3: the column and the
# schema already allow them, but saving an unusable configuration is refused.
ENABLED_PROVIDERS: tuple[AiProvider, ...] = ("anthropic",)

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
}
DEFAULT_MODELS: dict[str, str] = {
    provider: options[0].id for provider, options in PROVIDER_MODELS.items()
}


def _effective_model(provider: str, stored: str | None) -> str:
    """The stored model if it is still offered, else the provider default."""
    allowed = {option.id for option in PROVIDER_MODELS.get(provider, ())}
    if stored and stored in allowed:
        return stored
    return DEFAULT_MODELS.get(provider, "")


def _available_models() -> dict[str, list[AiModelOption]]:
    return {
        provider: list(options)
        for provider, options in PROVIDER_MODELS.items()
        if provider in ENABLED_PROVIDERS
    }


class _SettingsRepository(Protocol):
    def get_by_user_id(self, user_id: int) -> Any | None: ...

    def upsert(self, user_id: int, values: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class AiRuntimeConfig:
    """Everything the chat path needs. ``api_key`` is excluded from ``repr``."""

    provider: str
    model: str
    base_url: str | None
    api_key: str = field(repr=False)
    share_inventory_data: bool
    share_content_data: bool


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
                share_inventory_data=False,
                share_content_data=False,
                available_providers=list(ENABLED_PROVIDERS),
                available_models=_available_models(),
            )
        return UserAiSettingsResponse(
            enabled=bool(row.enabled),
            provider=row.provider,
            model=_effective_model(row.provider, row.model),
            base_url=row.base_url,
            api_key_set=row.api_key_encrypted is not None,
            share_inventory_data=bool(row.share_inventory_data),
            share_content_data=bool(row.share_content_data),
            available_providers=list(ENABLED_PROVIDERS),
            available_models=_available_models(),
        )

    def status(self, user_id: int, *, has_permission: bool) -> AiStatusResponse:
        """Availability = permission AND master switch AND a configured key."""
        if not has_permission:
            return AiStatusResponse(available=False, reason="no_permission")
        row = self._repo.get_by_user_id(user_id)
        if row is None or not row.enabled:
            return AiStatusResponse(available=False, reason="disabled")
        if row.api_key_encrypted is None:
            return AiStatusResponse(available=False, reason="not_configured")
        return AiStatusResponse(available=True, reason="ok")

    def resolve_api_key(self, user_id: int) -> str | None:
        """Decrypt the owner's key. The only read path that returns cleartext."""
        row = self._repo.get_by_user_id(user_id)
        if row is None or row.api_key_encrypted is None:
            return None
        try:
            cleartext = self._enc().decrypt(row.api_key_encrypted)
        except ValueError as exc:
            # The credential encryption secret was rotated since the key was saved.
            raise AiAssistantNotConfiguredError(
                "The stored API key can no longer be decrypted; please enter it again"
            ) from exc
        register_secret_value(cleartext)
        return cleartext

    def require_runtime_config(
        self, user_id: int, *, require_enabled: bool = True
    ) -> AiRuntimeConfig:
        """Server-side gate for every assistant endpoint that talks to a provider.

        ``require_enabled=False`` exists only for the connection test, so a user can verify
        a key before switching the assistant on.
        """
        row = self._repo.get_by_user_id(user_id)
        if row is None:
            if require_enabled:
                raise AiAssistantDisabledError("The AI assistant is disabled for this user")
            raise AiAssistantNotConfiguredError("No API key is configured")
        if require_enabled and not row.enabled:
            raise AiAssistantDisabledError("The AI assistant is disabled for this user")
        api_key = self.resolve_api_key(user_id)
        if not api_key:
            raise AiAssistantNotConfiguredError("No API key is configured")
        return AiRuntimeConfig(
            provider=row.provider,
            model=_effective_model(row.provider, row.model),
            base_url=row.base_url,
            api_key=api_key,
            share_inventory_data=bool(row.share_inventory_data),
            share_content_data=bool(row.share_content_data),
        )

    # -- writes --------------------------------------------------------------

    def update(self, user_id: int, data: UserAiSettingsUpdate) -> UserAiSettingsResponse:
        if data.api_key is not None and data.clear_api_key:
            raise AiSettingsValidationError("Provide either api_key or clear_api_key, not both")
        if data.provider is not None and data.provider not in ENABLED_PROVIDERS:
            raise AiSettingsValidationError(f"Provider {data.provider!r} is not available yet")

        values: dict[str, Any] = {}
        existing = self._repo.get_by_user_id(user_id)
        effective_provider = data.provider or (
            existing.provider if existing is not None else DEFAULT_PROVIDER
        )
        if data.model is not None and data.model not in {
            option.id for option in PROVIDER_MODELS.get(effective_provider, ())
        }:
            raise AiSettingsValidationError(
                f"Model {data.model!r} is not available for provider {effective_provider!r}"
            )

        if data.enabled is not None:
            values["enabled"] = data.enabled
        if data.provider is not None:
            values["provider"] = data.provider
            if data.model is None and (existing is None or existing.provider != data.provider):
                values["model"] = DEFAULT_MODELS[data.provider]
        if data.model is not None:
            values["model"] = data.model.strip()
        if data.share_inventory_data is not None:
            values["share_inventory_data"] = data.share_inventory_data
        if data.share_content_data is not None:
            values["share_content_data"] = data.share_content_data
        if data.api_key is not None:
            values["api_key_encrypted"] = self._enc().encrypt(data.api_key.get_secret_value())
        elif data.clear_api_key:
            values["api_key_encrypted"] = None
        if existing is None and "model" not in values:
            values["model"] = DEFAULT_MODELS[DEFAULT_PROVIDER]

        if values:
            self._repo.upsert(user_id, values)
        return self.get(user_id)

    def _enc(self) -> EncryptionService:
        if self._encryption is None:
            self._encryption = EncryptionService()
        return self._encryption
