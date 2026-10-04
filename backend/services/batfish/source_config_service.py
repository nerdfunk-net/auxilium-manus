"""Batfish source configuration: a host/port pair, no credential.

The coordinator has no authentication, so unlike every other source in this
app there is no vault credential to select -- non-secret config (``host``,
``port``) lives entirely in the generic ``settings`` table under
``sources.batfish.<id>``. Mirrors ``services.pyats.source_config_service``
minus the credential half.
"""

from __future__ import annotations

from typing import Any

from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.settings.source_config_base import (
    SourceConfigStore,
    SourceConflictError,
    SourceNotFoundError,
)


class BatfishSourceNotFoundError(SourceNotFoundError):
    display_name = "Batfish"


class BatfishSourceConflictError(SourceConflictError):
    display_name = "Batfish"


def _validate_host(host: str) -> str:
    normalized = (host or "").strip()
    if not normalized:
        raise BatfishValidationError("Batfish host is required")
    if len(normalized) > 255:
        raise BatfishValidationError("Batfish host must be 255 characters or fewer")
    return normalized


def _validate_target(host: str, port: int, *, resolve_dns: bool) -> str:
    """Apply the outbound HTTP policy to the coordinator target (B1).

    pybatfish turns ``host``/``port`` into ``http://{host}:{port}/v2/...``
    (``Session.get_base_url2``) and speaks unauthenticated HTTP to it, so the
    pair is subject to the same ``validate_outbound_http_url`` policy as every
    other source URL: no link-local / metadata targets, and loopback only when
    ``ALLOW_LOOPBACK_SOURCE_URLS=true`` (native-host development against
    ``127.0.0.1``). ``resolve_dns=True`` at CRUD/test time; ``False`` when a
    step resolves a stored source (no DNS on the worker hot path).
    """
    safe_host = _validate_host(host)
    try:
        validate_outbound_http_url(f"http://{safe_host}:{int(port)}", resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise BatfishValidationError(f"Batfish host is not allowed: {exc}") from exc
    return safe_host


class BatfishSourceConfigService(SourceConfigStore):
    source_type = "batfish"
    description_label = "Batfish source"
    not_found_error = BatfishSourceNotFoundError
    conflict_error = BatfishSourceConflictError

    def create_source(self, *, source_id: str, host: str, port: int = 9996) -> dict[str, Any]:
        key = self._new_setting_key(source_id)
        safe_host = _validate_target(host, port, resolve_dns=True)
        return self._persist_new(
            key=key, source_id=source_id, value={"host": safe_host, "port": port}
        )

    def update_source(
        self, source_id: str, *, host: str | None = None, port: int | None = None
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        updated_value = dict(setting.value)
        new_host = host if host is not None else str(updated_value.get("host") or "")
        new_port = port if port is not None else int(updated_value.get("port", 9996))
        # Re-validate the resulting pair whichever of the two changed (B1).
        updated_value["host"] = _validate_target(new_host, new_port, resolve_dns=True)
        updated_value["port"] = new_port
        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)

    def resolve_connection(self, source_id: str) -> BatfishConnection:
        value = self._get_setting_or_raise(source_id).value
        port = int(value.get("port", 9996))
        # Rows can predate the policy; re-check without DNS (B1).
        host = _validate_target(str(value["host"]), port, resolve_dns=False)
        return BatfishConnection(host=host, port=port)

    def resolve_inline_connection(self, *, host: str, port: int) -> BatfishConnection:
        """Build a connection from unsaved dialog values (no persisted source yet)."""
        return BatfishConnection(
            host=_validate_target(host, int(port), resolve_dns=True), port=int(port)
        )

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": value.get("source_id"),
            "host": value.get("host"),
            "port": value.get("port", 9996),
        }
