"""What ``collect-client-data`` and ``get-catalyst-center-client-data`` share around the store.

Both steps end in ``ClientDataService.store_device_collection`` (one collection per device and
run). This module holds that write, the summary stamped on the device, and the failure records
of the three storage outcomes (duplicate name, row cap, storage error), so the two steps differ
only in how they collect.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from core.config import settings
from core.database import get_db_session
from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
    ClientNeighborRow,
    TooManyRowsError,
)
from models.failure import FailureInfo
from models.workflow_context import Capability, DeviceContext, DeviceStatus
from services.client_data.client_data_service import ClientDataService
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.duplicate_keys import DUPLICATE_KEY_CODE, DUPLICATE_KEY_FAILURE
from workflow_steps.common.partial_outcomes import mark_device_failed

logger = logging.getLogger(__name__)

RESULT_KEY = "client_data"


class StorageRejected(Exception):  # noqa: N818 - internal signal, never leaves the steps
    """The storage service refused the values (its own ``ValueError``), not a step error."""


def ip_or_none(host: str | None) -> str | None:
    """``device_ip`` is a 45-character address column: a hostname or anything else is not stored."""
    try:
        return str(ipaddress.ip_address(host or ""))
    except ValueError:
        return None


def store_collection_sync(
    *,
    session_id: str,
    device_name: str,
    device_ip: str | None,
    ip_rows: Sequence[ClientIpRow],
    mac_rows: Sequence[ClientMacRow],
    hostname_rows: Sequence[ClientHostnameRow],
    status: ClientCollectionStatus,
    neighbor_rows: Sequence[ClientNeighborRow] = (),
    collected_at: datetime,
    target_host: str,
) -> None:
    """Write one device's collection in its own database session (call it in a thread)."""
    db = get_db_session()
    try:
        ClientDataService(db).store_device_collection(
            session_id=session_id,
            device_name=device_name,
            device_ip=device_ip,
            ip_rows=ip_rows,
            mac_rows=mac_rows,
            hostname_rows=hostname_rows,
            status=status,
            neighbor_rows=neighbor_rows,
            keep_sessions=settings.client_data_keep_sessions,
            collected_at=collected_at,
            target_host=target_host,
        )
    except ValueError as exc:  # the service validates names and session ids with ValueError
        raise StorageRejected(type(exc).__name__) from exc
    finally:
        db.close()


async def store_collection(store_lock: asyncio.Lock, **collection: Any) -> None:
    """One write at a time: each is short, and a large fan-out must not take a pooled database
    connection per device."""
    async with store_lock:
        await asyncio.to_thread(store_collection_sync, **collection)


def with_summary(device: DeviceContext, node_id: str, summary: dict[str, Any]) -> DeviceContext:
    """Write the summary under ``parsed.<node id>.client_data`` and stamp ``PARSED``.

    The registry promises ``produces: [parsed]``; the runner checks the capability on every
    device of the success outcome.
    """
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "parsed": set_node_result(device.parsed, node_id, RESULT_KEY, summary),
            "capabilities": device.capabilities | {Capability.PARSED},
        }
    )


def duplicate_failure(device: DeviceContext, node_id: str, *, step_id: str) -> DeviceContext:
    return mark_device_failed(
        device,
        node_id=node_id,
        step_id=step_id,
        code=DUPLICATE_KEY_CODE,
        message=(
            f"another device in this run has the same name as {device.name!r} (in this step or "
            "in another execution); client data is stored per device name"
        ),
        failure=DUPLICATE_KEY_FAILURE,
    )


def too_many_rows_failure(exc: TooManyRowsError) -> tuple[str, str, FailureInfo]:
    """``(code, message, failure)`` for a table above the row cap (one wording for both checks)."""
    return (
        "too_many_rows",
        f"The {exc.table} table has more rows than CLIENT_DATA_MAX_ROWS_PER_TABLE "
        f"({exc.limit}) allows; nothing was stored for this device",
        FailureInfo(phase="command", kind="payload_too_large"),
    )


def storage_failure(exc: Exception) -> tuple[str, str, FailureInfo]:
    """``(code, message, failure)`` for a storage error: the class name only, because database
    text can carry SQL and bound values."""
    logger.warning("client data storage failed error=%s", type(exc).__name__)
    return (
        "storage_failed",
        "The collected data could not be stored",
        FailureInfo(phase="internal", kind="internal_error", exception_type=type(exc).__name__),
    )
