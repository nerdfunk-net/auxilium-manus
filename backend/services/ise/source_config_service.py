"""Cisco ISE source configuration: pairs a settings entry with an encrypted credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.ise.<id>``; the username/password
live in the encrypted ``credentials`` table (source="ise") so the password is
never stored in plaintext.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.safe_urls import validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialNotFoundError
from services.ise.common.exceptions import ISEValidationError
from services.ise.credentials import ISECredentials
from services.settings.source_keys import build_source_key, ensure_value_source_id

CREDENTIAL_SOURCE = "ise"
CREDENTIAL_TYPE = "generic"


class ISESourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"ISE source '{source_id}' not found")
        self.source_id = source_id


class ISESourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"ISE source '{source_id}' already exists")
        self.source_id = source_id


def _credential_name(source_id: str) -> str:
    return f"ise-{source_id}"


class ISESourceConfigService:
    def __init__(self, db: Session) -> None:
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
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = build_source_key("ise", source_id)
        if self._settings.get_by_key(key) is not None:
            raise ISESourceConflictError(source_id)

        safe_url = validate_outbound_http_url(url, resolve_dns=True)

        # This credential is owned by the ISE source config itself, not by
        # any individual user, so it must always be global (never requires
        # an acting_user_id, never hidden from other users' resolution).
        credential = self._credentials.create_credential(
            name=_credential_name(source_id),
            username=username,
            cred_type=CREDENTIAL_TYPE,
            password=password,
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
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        credential_id = setting.value.get("credential_id")

        if credential_id is not None and (username is not None or password is not None):
            self._credentials.update_credential(
                credential_id,
                username=username,
                password=password,
            )

        updated_value = dict(setting.value)
        if url is not None:
            updated_value["url"] = validate_outbound_http_url(url, resolve_dns=True)
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
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> ISECredentials:
        """Resolve connection settings, layering any overrides on top of what's saved.

        Overrides let ``/test-connection`` validate unsaved edits (e.g. a password
        just typed into the source dialog) without requiring a Save first.
        """
        setting = self._get_setting_or_raise(source_id)
        value = setting.value

        resolved_url = (
            validate_outbound_http_url(url, resolve_dns=True) if url is not None else value["url"]
        )

        credential_id = value.get("credential_id")
        if username is not None and password is not None:
            resolved_username = username
            resolved_password = password
        else:
            if credential_id is None:
                raise ISEValidationError(f"ISE source '{source_id}' has no linked credential")
            credential = self._credentials.get_credential_by_id(credential_id)
            if credential is None:
                raise ISEValidationError(f"ISE source '{source_id}' credential is missing")
            resolved_username = username if username is not None else credential["username"]
            resolved_password = (
                password
                if password is not None
                else self._credentials.get_decrypted_password(credential_id)
            )

        return ISECredentials(
            base_url=resolved_url,
            username=resolved_username,
            password=resolved_password,
            timeout=float(timeout if timeout is not None else value.get("timeout", 30.0)),
            verify_ssl=bool(
                verify_ssl if verify_ssl is not None else value.get("verify_ssl", True)
            ),
        )

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("ise", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise ISESourceNotFoundError(source_id)
        return setting

    @staticmethod
    def _to_public(value: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in value.items() if k != "credential_id"}
