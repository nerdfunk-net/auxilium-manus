"""Mattermost source configuration: pairs a settings entry with an encrypted credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.mattermost.<id>``; the bearer
token lives in the encrypted ``credentials`` table (source="mattermost") so
it is never stored in plaintext. Mirrors ``services.pyats.source_config_service``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from core.config import settings
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialNotFoundError
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from services.settings.source_keys import build_source_key, ensure_value_source_id

CREDENTIAL_SOURCE = "mattermost"
CREDENTIAL_TYPE = "generic"
# The credential's username field is unused (auth is bearer-token-only) but
# CredentialsService requires one; a fixed sentinel keeps it self-explanatory.
_TOKEN_USERNAME = "mattermost-bot"


class MattermostSourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Mattermost source '{source_id}' not found")
        self.source_id = source_id


class MattermostSourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Mattermost source '{source_id}' already exists")
        self.source_id = source_id


def _credential_name(source_id: str) -> str:
    return f"mattermost-{source_id}"


def _validate_mattermost_url(url: str) -> str:
    """Validate + normalize a Mattermost URL, enforcing https outside development.

    Layers on top of ``validate_outbound_http_url`` (SSRF/RFC1918/loopback
    checks shared by every source). ``http://`` is only accepted when
    ``ENV=development`` (the default) — matches the policy already used for
    Git remotes in ``core.safe_urls.validate_git_remote_url``.
    """
    safe_url = validate_outbound_http_url(url, resolve_dns=True)
    scheme = urlparse(safe_url).scheme.lower()
    if scheme == "http" and settings.environment != "development":
        raise UnsafeURLError(
            "Mattermost URL must use https in this environment "
            "(set ENV=development to allow http)."
        )
    return safe_url


class MattermostSourceConfigService:
    def __init__(self, db: Session) -> None:
        self._settings = SettingsRepository(db)
        self._credentials = CredentialsService(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix="sources.mattermost.")
        return [self._to_public(row.value) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        return self._to_public(setting.value)

    def create_source(
        self,
        *,
        source_id: str,
        url: str,
        token: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = build_source_key("mattermost", source_id)
        if self._settings.get_by_key(key) is not None:
            raise MattermostSourceConflictError(source_id)

        safe_url = _validate_mattermost_url(url)

        # This credential is owned by the Mattermost source config itself,
        # not by any individual user, so it must always be global.
        credential = self._credentials.create_credential(
            name=_credential_name(source_id),
            username=_TOKEN_USERNAME,
            cred_type=CREDENTIAL_TYPE,
            password=token,
            source=CREDENTIAL_SOURCE,
            visibility="global",
        )
        value = ensure_value_source_id(
            {
                "url": safe_url,
                "verify_ssl": verify_ssl,
                "timeout": timeout,
                "credential_id": credential["id"],
            },
            source_type="mattermost",
            source_id=source_id,
        )
        setting = self._settings.create(
            key=key, value=value, description=f"Mattermost source {source_id}"
        )
        return self._to_public(setting.value)

    def update_source(
        self,
        source_id: str,
        *,
        url: str | None = None,
        token: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        credential_id = setting.value.get("credential_id")

        if credential_id is not None and token is not None:
            self._credentials.update_credential(credential_id, password=token)

        updated_value = dict(setting.value)
        if url is not None:
            updated_value["url"] = _validate_mattermost_url(url)
        if verify_ssl is not None:
            updated_value["verify_ssl"] = verify_ssl
        if timeout is not None:
            updated_value["timeout"] = timeout

        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)

    def delete_source(self, source_id: str) -> None:
        setting = self._get_setting_or_raise(source_id)
        credential_id = setting.value.get("credential_id")
        self._settings.delete(setting)
        if credential_id is not None:
            try:
                self._credentials.delete_credential(credential_id)
            except CredentialNotFoundError:
                pass

    def resolve_credentials(
        self,
        source_id: str,
        *,
        url: str | None = None,
        token: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> MattermostCredentials:
        """Resolve connection settings, layering any overrides on top of what's saved.

        Overrides let ``/test-connection`` validate unsaved edits (e.g. a token
        just typed into the source dialog) without requiring a Save first.
        """
        setting = self._get_setting_or_raise(source_id)
        value = setting.value

        resolved_url = _validate_mattermost_url(url) if url is not None else value["url"]

        if token is not None:
            resolved_token = token
        else:
            credential_id = value.get("credential_id")
            if credential_id is None:
                raise MattermostValidationError(
                    f"Mattermost source '{source_id}' has no linked credential"
                )
            credential = self._credentials.get_credential_by_id(credential_id)
            if credential is None:
                raise MattermostValidationError(
                    f"Mattermost source '{source_id}' credential is missing"
                )
            resolved_token = self._credentials.get_decrypted_password(credential_id)

        return MattermostCredentials(
            base_url=resolved_url,
            token=resolved_token,
            timeout=float(timeout if timeout is not None else value.get("timeout", 30.0)),
            verify_ssl=bool(
                verify_ssl if verify_ssl is not None else value.get("verify_ssl", True)
            ),
        )

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("mattermost", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise MattermostSourceNotFoundError(source_id)
        return setting

    @staticmethod
    def _to_public(value: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in value.items() if k != "credential_id"}
