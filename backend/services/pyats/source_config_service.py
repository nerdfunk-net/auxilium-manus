"""pyATS shim source configuration: pairs a settings entry with an encrypted credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.pyats.<id>``; the bearer token
lives in the encrypted ``credentials`` table (source="pyats") so it is never
stored in plaintext. Mirrors ``services.ise.source_config_service``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.safe_urls import validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialNotFoundError
from services.pyats.common.exceptions import PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.settings.source_keys import build_source_key, ensure_value_source_id

CREDENTIAL_SOURCE = "pyats"
CREDENTIAL_TYPE = "generic"
# The credential's username field is unused (auth is bearer-token-only) but
# CredentialsService requires one; a fixed sentinel keeps it self-explanatory.
_TOKEN_USERNAME = "pyats-shim"


class PyATSSourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"pyATS source '{source_id}' not found")
        self.source_id = source_id


class PyATSSourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"pyATS source '{source_id}' already exists")
        self.source_id = source_id


def _credential_name(source_id: str) -> str:
    return f"pyats-{source_id}"


class PyATSSourceConfigService:
    def __init__(self, db: Session) -> None:
        self._settings = SettingsRepository(db)
        self._credentials = CredentialsService(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix="sources.pyats.")
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
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = build_source_key("pyats", source_id)
        if self._settings.get_by_key(key) is not None:
            raise PyATSSourceConflictError(source_id)

        safe_url = validate_outbound_http_url(url, resolve_dns=True)

        # This credential is owned by the pyATS source config itself, not by
        # any individual user, so it must always be global.
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
            source_type="pyats",
            source_id=source_id,
        )
        setting = self._settings.create(
            key=key, value=value, description=f"pyATS shim source {source_id}"
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

    def resolve_credentials(self, source_id: str) -> PyATSCredentials:
        setting = self._get_setting_or_raise(source_id)
        value = setting.value
        credential_id = value.get("credential_id")
        if credential_id is None:
            raise PyATSValidationError(f"pyATS source '{source_id}' has no linked credential")
        credential = self._credentials.get_credential_by_id(credential_id)
        if credential is None:
            raise PyATSValidationError(f"pyATS source '{source_id}' credential is missing")
        token = self._credentials.get_decrypted_password(credential_id)
        return PyATSCredentials(
            base_url=value["url"],
            token=token,
            timeout=float(value.get("timeout", 30.0)),
            verify_ssl=bool(value.get("verify_ssl", False)),
        )

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("pyats", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise PyATSSourceNotFoundError(source_id)
        return setting

    @staticmethod
    def _to_public(value: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in value.items() if k != "credential_id"}
