"""Batfish source configuration: a host/port pair, no credential.

The coordinator has no authentication, so unlike every other source in this
app there is no vault credential to select -- non-secret config (``host``,
``port``) lives entirely in the generic ``settings`` table under
``sources.batfish.<id>``. Mirrors ``services.pyats.source_config_service``
minus the credential half.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from repositories.settings_repository import SettingsRepository
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.settings.source_keys import build_source_key, ensure_value_source_id


class BatfishSourceNotFoundError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Batfish source '{source_id}' not found")
        self.source_id = source_id


class BatfishSourceConflictError(Exception):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Batfish source '{source_id}' already exists")
        self.source_id = source_id


def _validate_host(host: str) -> str:
    normalized = (host or "").strip()
    if not normalized:
        raise BatfishValidationError("Batfish host is required")
    if len(normalized) > 255:
        raise BatfishValidationError("Batfish host must be 255 characters or fewer")
    return normalized


class BatfishSourceConfigService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = SettingsRepository(db)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._settings.list_all(key_prefix="sources.batfish.")
        return [self._to_public(row.value) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        return self._to_public(setting.value)

    def create_source(
        self,
        *,
        source_id: str,
        host: str,
        port: int = 9996,
    ) -> dict[str, Any]:
        key = build_source_key("batfish", source_id)
        if self._settings.get_by_key(key) is not None:
            raise BatfishSourceConflictError(source_id)

        safe_host = _validate_host(host)

        value = ensure_value_source_id(
            {"host": safe_host, "port": port},
            source_type="batfish",
            source_id=source_id,
        )
        setting = self._settings.create(
            key=key, value=value, description=f"Batfish source {source_id}"
        )
        return self._to_public(setting.value)

    def update_source(
        self,
        source_id: str,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)

        updated_value = dict(setting.value)
        if host is not None:
            updated_value["host"] = _validate_host(host)
        if port is not None:
            updated_value["port"] = port

        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)

    def delete_source(self, source_id: str) -> None:
        setting = self._get_setting_or_raise(source_id)
        self._settings.delete(setting)

    def resolve_connection(self, source_id: str) -> BatfishConnection:
        setting = self._get_setting_or_raise(source_id)
        value = setting.value
        return BatfishConnection(host=value["host"], port=int(value.get("port", 9996)))

    def resolve_inline_connection(self, *, host: str, port: int) -> BatfishConnection:
        """Build a connection from unsaved dialog values (no persisted source yet)."""
        return BatfishConnection(host=_validate_host(host), port=int(port))

    def _get_setting_or_raise(self, source_id: str) -> Any:
        key = build_source_key("batfish", source_id)
        setting = self._settings.get_by_key(key)
        if setting is None:
            raise BatfishSourceNotFoundError(source_id)
        return setting

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": value.get("source_id"),
            "host": value.get("host"),
            "port": value.get("port", 9996),
        }
