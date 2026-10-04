"""Shared implementation of the per-source configuration services.

A source (ISE, Catalyst Center, pyATS, Mattermost, Batfish) is a Settings row
``sources.<type>.<id>``. Credentialed HTTP sources additionally point at a global vault
credential by ``credential_id``. ``SourceConfigStore`` is the part every source needs;
``CredentialedHttpSourceService`` adds URL/credential handling. Each concrete service only
declares its names, defaults and how to build its credentials object.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy.orm import Session

from core.safe_urls import validate_source_transport
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)
from services.settings.source_keys import (
    SourceType,
    build_source_key,
    ensure_value_source_id,
    source_key_prefix,
)


class SourceNotFoundError(Exception):
    display_name: ClassVar[str] = "Source"

    def __init__(self, source_id: str) -> None:
        super().__init__(f"{self.display_name} source '{source_id}' not found")
        self.source_id = source_id


class SourceConflictError(Exception):
    display_name: ClassVar[str] = "Source"

    def __init__(self, source_id: str) -> None:
        super().__init__(f"{self.display_name} source '{source_id}' already exists")
        self.source_id = source_id


class SourceConfigStore:
    """list / get / delete and the settings-row plumbing shared by every source type."""

    source_type: ClassVar[SourceType]
    description_label: ClassVar[str]  # "Cisco ISE source" -> "Cisco ISE source lab"
    not_found_error: ClassVar[type[SourceNotFoundError]]
    conflict_error: ClassVar[type[SourceConflictError]]

    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = SettingsRepository(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix=source_key_prefix(self.source_type))
        return [self._to_public(row.value) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any]:
        return self._to_public(self._get_setting_or_raise(source_id).value)

    def delete_source(self, source_id: str) -> None:
        self._settings.delete(self._get_setting_or_raise(source_id))

    def _get_setting_or_raise(self, source_id: str) -> Any:
        setting = self._settings.get_by_key(build_source_key(self.source_type, source_id))
        if setting is None:
            raise self.not_found_error(source_id)
        return setting

    def _new_setting_key(self, source_id: str) -> str:
        """The settings key for a new source; raises ``conflict_error`` if it already exists."""
        key = build_source_key(self.source_type, source_id)
        if self._settings.get_by_key(key) is not None:
            raise self.conflict_error(source_id)
        return key

    def _persist_new(self, *, key: str, source_id: str, value: dict[str, Any]) -> dict[str, Any]:
        stored = ensure_value_source_id(value, source_type=self.source_type, source_id=source_id)
        setting = self._settings.create(
            key=key, value=stored, description=f"{self.description_label} {source_id}"
        )
        return self._to_public(setting.value)

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        return dict(value)


class CredentialedHttpSourceService[CredsT](SourceConfigStore):
    """A source with ``url`` / ``verify_ssl`` / ``timeout`` and a global ``credential_id``."""

    display_name: ClassVar[str]  # used in messages: "ISE", "Catalyst Center", "pyATS", ...
    validation_error: ClassVar[type[Exception]]
    default_verify_ssl: ClassVar[bool] = True
    requires_username: ClassVar[bool] = False  # basic-auth sources need username + secret

    def __init__(self, db: Session) -> None:
        super().__init__(db)
        self._credentials = CredentialsService(db)

    # -- hooks ---------------------------------------------------------------------

    def _validate_url(self, url: str, *, verify_ssl: bool) -> str:
        """The (url, verify_ssl) pair must satisfy the source transport policy."""
        return validate_source_transport(url, verify_ssl=verify_ssl, resolve_dns=True)

    def _build_credentials(
        self,
        *,
        base_url: str,
        username: str | None,
        secret: str,
        timeout: float,
        verify_ssl: bool,
    ) -> CredsT:
        raise NotImplementedError

    # -- write ---------------------------------------------------------------------

    def create_source(
        self,
        *,
        source_id: str,
        url: str,
        credential_id: int,
        verify_ssl: bool | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        key = self._new_setting_key(source_id)
        effective_verify_ssl = self.default_verify_ssl if verify_ssl is None else verify_ssl
        safe_url = self._validate_url(url, verify_ssl=effective_verify_ssl)
        self._assert_usable_credential(credential_id)
        return self._persist_new(
            key=key,
            source_id=source_id,
            value={
                "url": safe_url,
                "verify_ssl": effective_verify_ssl,
                "timeout": timeout,
                "credential_id": credential_id,
            },
        )

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
        if credential_id is not None:
            self._assert_usable_credential(credential_id)
            updated_value["credential_id"] = credential_id
        if verify_ssl is not None:
            updated_value["verify_ssl"] = verify_ssl
        if timeout is not None:
            updated_value["timeout"] = timeout
        if url is not None or verify_ssl is not None:
            # Validate the resulting (url, verify_ssl) pair whichever of the two changed.
            updated_value["url"] = self._validate_url(
                url if url is not None else str(updated_value["url"]),
                verify_ssl=bool(updated_value.get("verify_ssl", self.default_verify_ssl)),
            )
        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)

    # -- resolve (used by steps and the test-connection routes) ------------------------

    def resolve_credentials(
        self,
        source_id: str,
        *,
        url: str | None = None,
        credential_id: int | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ) -> CredsT:
        """Resolve saved connection settings, layering optional overrides on top.

        Overrides let ``/test-connection`` validate an edit to the saved source (e.g. a different
        credential picked in the dialog) without a Save first.
        """
        value = self._get_setting_or_raise(source_id).value
        effective_verify_ssl = bool(
            verify_ssl
            if verify_ssl is not None
            else value.get("verify_ssl", self.default_verify_ssl)
        )
        resolved_url = (
            self._validate_url(url, verify_ssl=effective_verify_ssl)
            if url is not None
            else value["url"]
        )
        effective_id = credential_id if credential_id is not None else value.get("credential_id")
        if effective_id is None:
            raise self.validation_error(
                f"{self.display_name} source '{source_id}' has no linked credential"
            )
        username, secret = self._resolve_secret(effective_id)
        return self._build_credentials(
            base_url=resolved_url,
            username=username,
            secret=secret,
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
    ) -> CredsT:
        """Build credentials from unsaved dialog values (no persisted source yet)."""
        safe_url = self._validate_url(url, verify_ssl=bool(verify_ssl))
        username, secret = self._resolve_secret(credential_id)
        return self._build_credentials(
            base_url=safe_url,
            username=username,
            secret=secret,
            timeout=float(timeout),
            verify_ssl=bool(verify_ssl),
        )

    # -- internals -------------------------------------------------------------------

    def _username_required_message(self) -> str:
        return (
            f"Selected credential has no username; {self.display_name} "
            "requires a username + secret."
        )

    def _assert_usable_credential(self, credential_id: int) -> None:
        try:
            credential = assert_global_credential(
                self._db, credential_id, source_type=self.source_type
            )
        except SourceCredentialError as exc:
            raise self.validation_error(str(exc)) from exc
        if self.requires_username and not credential.get("username"):
            raise self.validation_error(self._username_required_message())

    def _resolve_secret(self, credential_id: int) -> tuple[str | None, str]:
        try:
            username, secret = resolve_global_secret(
                self._db, credential_id, source_type=self.source_type
            )
        except SourceCredentialError as exc:
            raise self.validation_error(str(exc)) from exc
        if self.requires_username and not username:
            raise self.validation_error(self._username_required_message())
        return username, secret

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
