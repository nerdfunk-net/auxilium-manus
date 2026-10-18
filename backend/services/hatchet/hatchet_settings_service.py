from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from importlib.metadata import version as package_version
from urllib.parse import urlsplit, urlunsplit

from hatchet.client import hatchet
from hatchet.dynamic_worker_config import (
    DYNAMIC_WORKER_NAME,
    DYNAMIC_WORKER_POLL_INTERVAL_SECONDS,
    DYNAMIC_WORKER_SLOTS,
)
from hatchet.worker_config import WORKER_NAME, WORKER_SLOTS
from models.hatchet import HatchetConfigResponse, HatchetStatusResponse

logger = logging.getLogger(__name__)


def _dashboard_base_url() -> str:
    """Browser-reachable base URL, without any ``user:password@`` part (it reaches the browser)."""
    raw = os.environ.get("HATCHET_DASHBOARD_URL") or hatchet.config.server_url
    parts = urlsplit(raw)
    if "@" not in parts.netloc:
        return raw
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, "", ""))


def dashboard_run_url(hatchet_run_id: str | None) -> str | None:
    """Browser link to one run in the Hatchet dashboard; None when the run was never dispatched."""
    if not hatchet_run_id:
        return None
    tenant_id = hatchet.config.tenant_id
    if not tenant_id:
        return None
    return f"{_dashboard_base_url().rstrip('/')}/tenants/{tenant_id}/runs/{hatchet_run_id}"


def _build_config() -> HatchetConfigResponse:
    config = hatchet.config
    dashboard_url = _dashboard_base_url()
    return HatchetConfigResponse(
        server_url=config.server_url,
        dashboard_url=dashboard_url,
        host_port=config.host_port,
        tenant_id=config.tenant_id,
        namespace=config.namespace,
        tls_strategy=config.tls_config.strategy,
        debug=config.debug,
        token_configured=bool(config.token),
        worker_name=WORKER_NAME,
        worker_slots=WORKER_SLOTS,
        dynamic_worker_name=DYNAMIC_WORKER_NAME,
        dynamic_worker_slots=DYNAMIC_WORKER_SLOTS,
        dynamic_worker_poll_interval_seconds=DYNAMIC_WORKER_POLL_INTERVAL_SECONDS,
        sdk_version=package_version("hatchet-sdk"),
    )


async def _check_grpc_reachable(host_port: str) -> tuple[bool, str]:
    try:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    except ValueError:
        return False, f"Invalid host_port format: {host_port!r}"

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0,
        )
        writer.close()
        await writer.wait_closed()
        return True, ""
    except TimeoutError:
        return False, f"Timed out connecting to {host_port} (gRPC)"
    except (ConnectionRefusedError, OSError) as exc:
        return False, f"Cannot reach {host_port} (gRPC): {exc}"


async def _check_rest_reachable() -> tuple[bool, str]:
    """Exercise the REST client, not just a raw socket — this is what actually
    catches a misconfigured/stale `server_url` (e.g. a token whose embedded
    server_url claim no longer matches where the Hatchet API is deployed).
    """
    try:
        await hatchet.cron.aio_list(limit=1)
        return True, ""
    except Exception as exc:
        return False, f"REST API unreachable at {hatchet.config.server_url}: {exc}"


class HatchetSettingsService:
    def get_config(self) -> HatchetConfigResponse:
        return _build_config()

    async def check_connection(self) -> HatchetStatusResponse:
        config = _build_config()
        grpc_ok, grpc_message = await _check_grpc_reachable(config.host_port)
        rest_ok, rest_message = await _check_rest_reachable()

        reachable = grpc_ok and rest_ok
        if reachable:
            message = f"Connected — gRPC at {config.host_port}, REST at {config.server_url}"
        else:
            message = " / ".join(m for m in (grpc_message, rest_message) if m)

        return HatchetStatusResponse(
            **config.model_dump(),
            reachable=reachable,
            message=message,
            checked_at=datetime.now(UTC),
        )
