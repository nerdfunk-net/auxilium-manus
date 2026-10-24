"""Global AI proxy settings (doc/ai_integration/AI_ASSISTANT.md, "Proxy").

One ``settings`` row holds ``{enabled, url, credential_id, bypass_hosts}``. The proxy login is a
global Basic Auth (``generic``) credential referenced by id; its password is decrypted only in
``resolve`` and is never stored here, returned, or logged.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from models.ai_assistant import AiProxySettingsResponse, AiProxySettingsUpdate
from repositories.settings_repository import SettingsRepository
from services.ai_assistant.base_url_policy import BaseUrlPolicyError, validate_proxy_url
from services.ai_assistant.exceptions import (
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.providers.proxy import (
    BypassEntryError,
    ProxyConfig,
    parse_bypass_entry,
)
from services.ai_assistant.proxy_key import AI_PROXY_SETTINGS_KEY
from services.credentials.credentials_service import CredentialsService
from services.credentials.manager import CredentialManager
from services.credentials.secrets import CredentialLookupError, CredentialUnusableError

logger = logging.getLogger(__name__)

# Basic Auth in the credential manager.
PROXY_CREDENTIAL_TYPES = frozenset({"generic"})


class AiProxySettingsService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = SettingsRepository(db)

    # -- reads ---------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        row = self._repo.get_by_key(AI_PROXY_SETTINGS_KEY)
        return dict(row.value) if row is not None and isinstance(row.value, dict) else {}

    def get(self) -> AiProxySettingsResponse:
        value = self._load()
        credential_id = value.get("credential_id")
        if not isinstance(credential_id, int) or isinstance(credential_id, bool):
            credential_id = None
        credential = (
            CredentialsService(self._db).get_credential_by_id(credential_id)
            if credential_id is not None
            else None
        )
        enabled = value.get("enabled") is True
        raw_url = value.get("url")
        url = raw_url if isinstance(raw_url, str) else ""
        return AiProxySettingsResponse(
            enabled=enabled,
            url=url,
            credential_id=credential_id,
            credential_name=credential.get("name") if credential else None,
            bypass_hosts=[h for h in value.get("bypass_hosts", []) if isinstance(h, str)],
            configured=enabled and bool(url),
        )

    def is_enabled(self) -> bool:
        return self.get().configured

    def resolve(self) -> ProxyConfig | None:
        """The proxy to use for a provider call, or ``None`` when none is enabled.

        A broken credential never falls back to a direct connection: that would send traffic the
        administrator meant to keep inside the proxy around it.
        """
        value = self._load()
        if value.get("enabled") is not True or not value.get("url"):
            return None
        username: str | None = None
        password = ""
        credential_id = value.get("credential_id")
        if credential_id is not None:
            try:
                secret = CredentialManager(self._db).source_secret(
                    credential_id, allowed_types=PROXY_CREDENTIAL_TYPES
                )
            except (CredentialLookupError, CredentialUnusableError) as exc:
                logger.warning("AI proxy credential %s is unusable", credential_id)
                raise AiAssistantNotConfiguredError(
                    "The AI proxy credential is missing or unusable; ask an administrator"
                ) from exc
            username, password = secret.username or "", secret.password
        return ProxyConfig(
            url=value["url"],
            username=username,
            password=password,
            bypass_hosts=tuple(value.get("bypass_hosts", ())),
        )

    # -- writes --------------------------------------------------------------

    def update(
        self, data: AiProxySettingsUpdate, *, actor_user_id: int | None = None
    ) -> AiProxySettingsResponse:
        url = data.url
        if data.enabled and not url:
            raise AiSettingsValidationError("A proxy URL is required")
        if url:
            try:
                url = validate_proxy_url(url)
            except BaseUrlPolicyError as exc:
                raise AiSettingsValidationError(str(exc)) from exc
        for entry in data.bypass_hosts:
            try:
                parse_bypass_entry(entry)
            except BypassEntryError as exc:
                raise AiSettingsValidationError(str(exc)) from exc
        if data.credential_id is not None:
            try:
                CredentialManager(self._db).source_credential(
                    data.credential_id, allowed_types=PROXY_CREDENTIAL_TYPES
                )
            except (CredentialLookupError, CredentialUnusableError) as exc:
                raise AiSettingsValidationError(str(exc)) from exc
        value = {
            "enabled": data.enabled,
            "url": url,
            "credential_id": data.credential_id,
            "bypass_hosts": data.bypass_hosts,
        }
        row = self._repo.get_by_key(AI_PROXY_SETTINGS_KEY)
        if row is None:
            self._repo.create(
                key=AI_PROXY_SETTINGS_KEY, value=value, description="AI assistant outbound proxy"
            )
        else:
            self._repo.update(row, {"value": value})
        # Who and which switches, never the URL (internal topology) or the secret.
        logger.info(
            "ai_proxy_changed actor_user_id=%s enabled=%s credential_set=%s bypass_count=%s",
            actor_user_id,
            data.enabled,
            bool(data.credential_id),
            len(data.bypass_hosts),
        )
        return self.get()
