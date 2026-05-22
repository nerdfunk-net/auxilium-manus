from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models.hatchet import (
    HatchetSettingsResponse,
    HatchetSettingsUpdate,
    HatchetStatusResponse,
)
from repositories.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "hatchet.config"
_DEFAULTS: dict[str, Any] = {
    "host_port": "localhost:7077",
    "dashboard_url": "http://localhost:8888",
    "debug": False,
    "worker_name": "auxilium-manus-worker",
    "worker_slots": 10,
}


def _env_defaults() -> dict[str, Any]:
    """Return config values from env vars that override hard-coded defaults."""
    result: dict[str, Any] = {}
    host_port = os.environ.get("HATCHET_CLIENT_HOST_PORT")
    if host_port:
        result["host_port"] = host_port
    token = os.environ.get("HATCHET_CLIENT_TOKEN")
    if token:
        result["token"] = token
    debug_raw = os.environ.get("HATCHET_CLIENT_DEBUG")
    if debug_raw is not None:
        result["debug"] = debug_raw.lower() in {"1", "true", "yes", "on"}
    return result


def _merge(stored: dict[str, Any]) -> dict[str, Any]:
    """Merge hard-coded defaults → env vars → stored DB values."""
    merged = {**_DEFAULTS, **_env_defaults(), **stored}
    return merged


class HatchetSettingsService:
    def __init__(self, db: Session) -> None:
        self._repo = SettingsRepository(db)

    def get_settings(self) -> HatchetSettingsResponse:
        row = self._repo.get_by_key(_SETTINGS_KEY)
        stored: dict[str, Any] = row.value if row else {}
        cfg = _merge(stored)
        return HatchetSettingsResponse(
            host_port=cfg.get("host_port", _DEFAULTS["host_port"]),
            dashboard_url=cfg.get("dashboard_url", _DEFAULTS["dashboard_url"]),
            debug=bool(cfg.get("debug", _DEFAULTS["debug"])),
            worker_name=cfg.get("worker_name", _DEFAULTS["worker_name"]),
            worker_slots=int(cfg.get("worker_slots", _DEFAULTS["worker_slots"])),
            token_configured=bool(cfg.get("token", "")),
        )

    def update_settings(self, data: HatchetSettingsUpdate) -> HatchetSettingsResponse:
        row = self._repo.get_by_key(_SETTINGS_KEY)
        stored: dict[str, Any] = dict(row.value) if row else {}

        if data.host_port is not None:
            stored["host_port"] = data.host_port
        if data.token is not None and data.token.strip():
            stored["token"] = data.token.strip()
        if data.dashboard_url is not None:
            stored["dashboard_url"] = data.dashboard_url
        if data.debug is not None:
            stored["debug"] = data.debug
        if data.worker_name is not None:
            stored["worker_name"] = data.worker_name
        if data.worker_slots is not None:
            stored["worker_slots"] = data.worker_slots

        if row is None:
            logger.info("Creating Hatchet settings")
            self._repo.create(
                key=_SETTINGS_KEY,
                value=stored,
                description="Hatchet engine configuration",
            )
        else:
            logger.info("Updating Hatchet settings")
            self._repo.update(row, {"value": stored})

        cfg = _merge(stored)
        return HatchetSettingsResponse(
            host_port=cfg.get("host_port", _DEFAULTS["host_port"]),
            dashboard_url=cfg.get("dashboard_url", _DEFAULTS["dashboard_url"]),
            debug=bool(cfg.get("debug", _DEFAULTS["debug"])),
            worker_name=cfg.get("worker_name", _DEFAULTS["worker_name"]),
            worker_slots=int(cfg.get("worker_slots", _DEFAULTS["worker_slots"])),
            token_configured=bool(cfg.get("token", "")),
        )

    async def get_status(self) -> HatchetStatusResponse:
        row = self._repo.get_by_key(_SETTINGS_KEY)
        stored: dict[str, Any] = row.value if row else {}
        cfg = _merge(stored)

        host_port: str = cfg.get("host_port", _DEFAULTS["host_port"])
        dashboard_url: str = cfg.get("dashboard_url", _DEFAULTS["dashboard_url"])
        token_configured = bool(cfg.get("token", ""))

        reachable, message = await _check_grpc_reachable(host_port)

        return HatchetStatusResponse(
            reachable=reachable,
            token_configured=token_configured,
            host_port=host_port,
            dashboard_url=dashboard_url,
            message=message,
            checked_at=datetime.now(timezone.utc),
        )


async def _check_grpc_reachable(host_port: str) -> tuple[bool, str]:
    try:
        parts = host_port.rsplit(":", 1)
        if len(parts) != 2:
            return False, f"Invalid host_port format: {host_port!r}"
        host, port_str = parts
        port = int(port_str)
    except ValueError:
        return False, f"Invalid port in host_port: {host_port!r}"

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0,
        )
        writer.close()
        await writer.wait_closed()
        return True, f"Reachable at {host_port}"
    except asyncio.TimeoutError:
        return False, f"Timed out connecting to {host_port}"
    except (ConnectionRefusedError, OSError) as exc:
        return False, f"Cannot reach {host_port}: {exc}"
