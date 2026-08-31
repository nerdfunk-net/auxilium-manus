"""Mattermost source configuration: pairs a settings entry with a vault credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.mattermost.<id>``; the personal
access token is a user-selected credential from the ``credentials`` vault,
referenced by ``credential_id``. The credential must be global (see
``services.credentials.source_credentials``). Mirrors
``services.pyats.source_config_service``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from core.config import settings
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from services.settings.source_keys import build_source_key, ensure_value_source_id


class MattermostSourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Mattermost source '{source_id}' not found")
        self.source_id = source_id


class MattermostSourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Mattermost source '{source_id}' already exists")
        self.source_id = source_id


def _validate_mattermost_url(url: str) -> str:
    """Validate + normalize a Mattermost URL, enforcing https outside development.

    Layers on top of ``validate_outbound_http_url`` (SSRF/RFC1918/loopback
    checks shared by every source). ``http://`` is only accepted when
    ``ENV=development`` (the default) -- matches the policy already used for
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
        self._db = db
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
        credential_id: int,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = build_source_key("mattermost", source_id)
        if self._settings.get_by_key(key) is not None:
            raise MattermostSourceConflictError(source_id)

        safe_url = _validate_mattermost_url(url)
        assert_global_credential(self._db, credential_id)

        value = ensure_value_source_id(
            {
                "url": safe_url,
                "verify_ssl": verify_ssl,
                "timeout": timeout,
                "credential_id": credential_id,
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
        credential_id: int | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)

        updated_value = dict(setting.value)
        if url is not None:
            updated_value["url"] = _validate_mattermost_url(url)
        if credential_id is not None:
            assert_global_credential(self._db, credential_id)
            updated_value["credential_id"] = credential_id
        if verify_ssl is not None:
            updated_value["verify_ssl"] = verify_ssl
        if timeout is not None:
            updated_value["timeout"] = timeout

        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)

    def delete_source(self, source_id: str) -> None:
        setting = self._get_setting_or_raise(source_id)
        self._settings.delete(setting)

    def resolve_credentials(
        self,
        source_id: str,
        *,
        url: str | None = None,
        credential_id: int | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> MattermostCredentials:
        """Resolve saved connection settings, layering optional overrides on top."""
        setting = self._get_setting_or_raise(source_id)
        value = setting.value

        resolved_url = _validate_mattermost_url(url) if url is not None else value["url"]
        effective_id = credential_id if credential_id is not None else value.get("credential_id")
        if effective_id is None:
            raise MattermostValidationError(
                f"Mattermost source '{source_id}' has no linked credential"
            )
        _, resolved_token = self._resolve_secret(effective_id)

        return MattermostCredentials(
            base_url=resolved_url,
            token=resolved_token,
            timeout=float(timeout if timeout is not None else value.get("timeout", 30.0)),
            verify_ssl=bool(
                verify_ssl if verify_ssl is not None else value.get("verify_ssl", True)
            ),
        )

    def resolve_inline_credentials(
        self,
        *,
        url: str,
        credential_id: int,
        verify_ssl: bool,
        timeout: float,
    ) -> MattermostCredentials:
        """Build credentials from unsaved dialog values (no persisted source yet)."""
        safe_url = _validate_mattermost_url(url)
        _, token = self._resolve_secret(credential_id)
        return MattermostCredentials(
            base_url=safe_url, token=token, timeout=float(timeout), verify_ssl=bool(verify_ssl)
        )

    def _resolve_secret(self, credential_id: int) -> tuple[str | None, str]:
        try:
            return resolve_global_secret(self._db, credential_id)
        except SourceCredentialError as exc:
            raise MattermostValidationError(str(exc)) from exc

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("mattermost", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise MattermostSourceNotFoundError(source_id)
        return setting

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        credential_id = value.get("credential_id")
        return {
            **value,
            "credential_id": credential_id,
            "credential_name": self._credential_name(credential_id),
        }

    def _credential_name(self, credential_id: Any) -> str | None:
        if not isinstance(credential_id, int):
            return None
        credential = self._credentials.get_credential_by_id(credential_id)
        return credential.get("name") if credential is not None else None
