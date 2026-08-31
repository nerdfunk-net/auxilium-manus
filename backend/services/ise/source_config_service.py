"""Cisco ISE source configuration: pairs a settings entry with a vault credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.ise.<id>``; the username + password
are a user-selected credential from the ``credentials`` vault, referenced by
``credential_id``. ISE authenticates with basic auth, so the chosen credential
must carry a non-empty username. The credential must be global (see
``services.credentials.source_credentials``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.safe_urls import validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)
from services.ise.common.exceptions import ISEValidationError
from services.ise.credentials import ISECredentials
from services.settings.source_keys import build_source_key, ensure_value_source_id


class ISESourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"ISE source '{source_id}' not found")
        self.source_id = source_id


class ISESourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"ISE source '{source_id}' already exists")
        self.source_id = source_id


class ISESourceConfigService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = SettingsRepository(db)
        self._credentials = CredentialsService(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix="sources.ise.")
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
        key = build_source_key("ise", source_id)
        if self._settings.get_by_key(key) is not None:
            raise ISESourceConflictError(source_id)

        safe_url = validate_outbound_http_url(url, resolve_dns=True)
        credential = assert_global_credential(self._db, credential_id)
        if not credential.get("username"):
            raise ISEValidationError(
                "Selected credential has no username; ISE requires a username + secret."
            )

        value = ensure_value_source_id(
            {
                "url": safe_url,
                "verify_ssl": verify_ssl,
                "timeout": timeout,
                "credential_id": credential_id,
            },
            source_type="ise",
            source_id=source_id,
        )
        setting = self._settings.create(
            key=key, value=value, description=f"Cisco ISE source {source_id}"
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
            updated_value["url"] = validate_outbound_http_url(url, resolve_dns=True)
        if credential_id is not None:
            credential = assert_global_credential(self._db, credential_id)
            if not credential.get("username"):
                raise ISEValidationError(
                    "Selected credential has no username; ISE requires a username + secret."
                )
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
    ) -> ISECredentials:
        """Resolve saved connection settings, layering optional overrides on top."""
        setting = self._get_setting_or_raise(source_id)
        value = setting.value

        resolved_url = (
            validate_outbound_http_url(url, resolve_dns=True) if url is not None else value["url"]
        )
        effective_id = credential_id if credential_id is not None else value.get("credential_id")
        if effective_id is None:
            raise ISEValidationError(f"ISE source '{source_id}' has no linked credential")
        username, password = self._resolve_secret(effective_id)
        if not username:
            raise ISEValidationError(
                "Selected credential has no username; ISE requires a username + secret."
            )

        return ISECredentials(
            base_url=resolved_url,
            username=username,
            password=password,
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
    ) -> ISECredentials:
        """Build credentials from unsaved dialog values (no persisted source yet)."""
        safe_url = validate_outbound_http_url(url, resolve_dns=True)
        username, password = self._resolve_secret(credential_id)
        if not username:
            raise ISEValidationError(
                "Selected credential has no username; ISE requires a username + secret."
            )
        return ISECredentials(
            base_url=safe_url,
            username=username,
            password=password,
            timeout=float(timeout),
            verify_ssl=bool(verify_ssl),
        )

    def _resolve_secret(self, credential_id: int) -> tuple[str | None, str]:
        try:
            return resolve_global_secret(self._db, credential_id)
        except SourceCredentialError as exc:
            raise ISEValidationError(str(exc)) from exc

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("ise", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise ISESourceNotFoundError(source_id)
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
