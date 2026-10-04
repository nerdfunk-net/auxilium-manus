"""Cisco Catalyst Center source configuration: a settings entry plus a vault credential.

Non-secret connection settings (URL, verify_ssl, timeout) live in the generic ``settings``
table under ``sources.catalyst_center.<id>``; the username + password are a user-selected
credential from the ``credentials`` vault, referenced by ``credential_id``. Catalyst Center's
token endpoint uses HTTP Basic auth, so the credential must carry a username. The credential
must be global (see ``services.credentials.source_credentials``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.safe_urls import validate_source_transport
from repositories.settings_repository import SettingsRepository
from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)
from services.settings.source_keys import build_source_key, ensure_value_source_id

_SOURCE_TYPE = "catalyst_center"
_USERNAME_REQUIRED = (
    "Selected credential has no username; Catalyst Center requires a username + secret."
)


class CatalystCenterSourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Catalyst Center source '{source_id}' not found")
        self.source_id = source_id


class CatalystCenterSourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Catalyst Center source '{source_id}' already exists")
        self.source_id = source_id


class CatalystCenterSourceConfigService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = SettingsRepository(db)
        self._credentials = CredentialsService(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix=build_source_key(_SOURCE_TYPE, "x")[:-1])
        return [self._to_public(row.value) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any]:
        return self._to_public(self._get_setting_or_raise(source_id).value)

    def create_source(
        self,
        *,
        source_id: str,
        url: str,
        credential_id: int,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = build_source_key(_SOURCE_TYPE, source_id)
        if self._settings.get_by_key(key) is not None:
            raise CatalystCenterSourceConflictError(source_id)

        safe_url = validate_source_transport(url, verify_ssl=verify_ssl, resolve_dns=True)
        self._assert_usable_credential(credential_id)

        value = ensure_value_source_id(
            {
                "url": safe_url,
                "verify_ssl": verify_ssl,
                "timeout": timeout,
                "credential_id": credential_id,
            },
            source_type=_SOURCE_TYPE,
            source_id=source_id,
        )
        setting = self._settings.create(
            key=key, value=value, description=f"Cisco Catalyst Center source {source_id}"
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
        changes: dict[str, Any] = {}
        if credential_id is not None:
            self._assert_usable_credential(credential_id)
            changes["credential_id"] = credential_id
        if verify_ssl is not None:
            changes["verify_ssl"] = verify_ssl
        if timeout is not None:
            changes["timeout"] = timeout
        merged = {**setting.value, **changes}
        if url is not None or verify_ssl is not None:
            # Validate the resulting (url, verify_ssl) pair whichever of the two changed.
            merged["url"] = validate_source_transport(
                url if url is not None else str(merged["url"]),
                verify_ssl=bool(merged.get("verify_ssl", True)),
                resolve_dns=True,
            )

        updated = self._settings.update(setting, {"value": merged})
        return self._to_public(updated.value)

    def delete_source(self, source_id: str) -> None:
        self._settings.delete(self._get_setting_or_raise(source_id))

    def resolve_credentials(
        self,
        source_id: str,
        *,
        url: str | None = None,
        credential_id: int | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> CatalystCenterCredentials:
        """Resolve saved connection settings, layering optional overrides on top."""
        value = self._get_setting_or_raise(source_id).value
        effective_id = credential_id if credential_id is not None else value.get("credential_id")
        if effective_id is None:
            raise CatalystCenterValidationError(
                f"Catalyst Center source '{source_id}' has no linked credential"
            )
        username, password = self._resolve_secret(effective_id)
        effective_verify_ssl = bool(
            verify_ssl if verify_ssl is not None else value.get("verify_ssl", True)
        )
        return CatalystCenterCredentials(
            base_url=(
                validate_source_transport(url, verify_ssl=effective_verify_ssl, resolve_dns=True)
                if url is not None
                else value["url"]
            ),
            username=username,
            password=password,
            timeout=float(timeout if timeout is not None else value.get("timeout", 30.0)),
            verify_ssl=effective_verify_ssl,
        )

    def resolve_inline_credentials(
        self,
        *,
        url: str,
        credential_id: int,
        verify_ssl: bool,
        timeout: float,
    ) -> CatalystCenterCredentials:
        """Build credentials from unsaved dialog values (no persisted source yet)."""
        username, password = self._resolve_secret(credential_id)
        return CatalystCenterCredentials(
            base_url=validate_source_transport(url, verify_ssl=verify_ssl, resolve_dns=True),
            username=username,
            password=password,
            timeout=float(timeout),
            verify_ssl=bool(verify_ssl),
        )

    def _assert_usable_credential(self, credential_id: int) -> None:
        try:
            credential = assert_global_credential(
                self._db, credential_id, source_type="catalyst_center"
            )
        except SourceCredentialError as exc:
            raise CatalystCenterValidationError(str(exc)) from exc
        if not credential.get("username"):
            raise CatalystCenterValidationError(_USERNAME_REQUIRED)

    def _resolve_secret(self, credential_id: int) -> tuple[str, str]:
        try:
            username, password = resolve_global_secret(
                self._db, credential_id, source_type="catalyst_center"
            )
        except SourceCredentialError as exc:
            raise CatalystCenterValidationError(str(exc)) from exc
        if not username:
            raise CatalystCenterValidationError(_USERNAME_REQUIRED)
        return username, password

    def _get_setting_or_raise(self, source_id: str) -> Any:
        setting = self._settings.get_by_key(build_source_key(_SOURCE_TYPE, source_id))
        if setting is None:
            raise CatalystCenterSourceNotFoundError(source_id)
        return setting

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        credential_id = value.get("credential_id")
        return {**value, "credential_name": self._credential_name(credential_id)}

    def _credential_name(self, credential_id: Any) -> str | None:
        if not isinstance(credential_id, int):
            return None
        credential = self._credentials.get_credential_by_id(credential_id)
        return credential.get("name") if credential is not None else None
