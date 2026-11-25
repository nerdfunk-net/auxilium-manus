"""Executor for the get-catalyst-center-client-data step.

Reads the wired clients of each device from Cisco Catalyst Center (no SSH) and stores them in
the client data tables like ``collect-client-data`` does: one collection per device and run, with
the MAC table (MAC, VLAN, port) and the ARP-like table (IP, MAC, VLAN). Devices are keyed by name.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

import service_factory
from core.models.runs import WorkflowRun
from models.catalyst_center_facts import CatalystCenterClient
from models.client_data import (
    ClientCollectionStatus,
    CollectionConflictError,
    TooManyRowsError,
)
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.catalyst_center.common.exceptions import CatalystCenterError
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_targets import (
    resolve_source_credentials,
    split_targets,
)
from workflow_steps.common.client_data_store import (
    StorageRejected,
    duplicate_failure,
    ip_or_none,
    storage_failure,
    store_collection,
    too_many_rows_failure,
    with_summary,
)
from workflow_steps.common.device_outcomes import build_outcomes, failed_device
from workflow_steps.common.duplicate_keys import (
    find_duplicate_keys,
)
from workflow_steps.common.fact_entries import MAX_PARALLEL_DEVICES
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag, record_dry_run
from workflow_steps.get_catalyst_center_client_data.mapping import map_clients

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "get-catalyst-center-client-data"
DEFAULT_LOOKBACK_HOURS = 24
MAX_LOOKBACK_HOURS = 168
_CATALYST_ERROR = "catalyst_center_error"


def _belongs_to(client: CatalystCenterClient, device_id: str) -> bool:
    """Keep only a client the controller attributes to this very switch (its UUID)."""
    return client.connected_device_id == device_id


async def _collect_one(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    session_id: str,
    lookback_hours: int,
    dry_run: bool,
    credentials: CatalystCenterCredentials,
    store_lock: asyncio.Lock,
    gate: asyncio.Semaphore,
) -> tuple[DeviceContext, bool]:
    if dry_run:
        payload = {"would_query": True, "device_id": device_id, "lookback_hours": lookback_hours}
        previewed = record_dry_run(device, node_id=node_id, payload=payload)
        return with_summary(previewed, node_id, {"dry_run": True}), True
    try:
        # Stamped when the query starts, so the per-device ordering follows when it ran.
        collected_at = datetime.now(UTC)
        service = service_factory.build_catalyst_center_client_data_service(credentials)
        async with gate:
            clients = await service.get_wired_clients(device_id, lookback_hours=lookback_hours)
        ip_rows, mac_rows = map_clients(
            (c for c in clients if _belongs_to(c, device_id)), platform=device.platform or ""
        )
        if clients and not mac_rows:
            # The controller answered with clients but none is usable (another switch, no MAC):
            # that is not "no clients", and storing it would replace the device's good data.
            return (
                failed_device(
                    device,
                    step_id=STEP_ID,
                    node_id=node_id,
                    code="no_usable_clients",
                    message=(
                        f"Catalyst Center returned {len(clients)} client(s) for the device but "
                        "none could be stored (no MAC address, or attributed to another "
                        "switch); nothing was stored"
                    ),
                    failure=FailureInfo(phase="api", kind="invalid_response"),
                ),
                False,
            )
        await store_collection(
            store_lock,
            session_id=session_id,
            device_name=device.name,
            device_ip=ip_or_none(device.primary_ip4),
            ip_rows=ip_rows,
            mac_rows=mac_rows,
            hostname_rows=[],
            # An empty answer is an observation too: it supersedes the device's older rows.
            status=ClientCollectionStatus(arp_status="ok", mac_status="ok"),
            collected_at=collected_at,
            target_host=f"catalyst_center:{device.source_id}:{device_id}"[:255],
        )
    except CatalystCenterError as exc:
        return (
            failed_device(
                device,
                step_id=STEP_ID,
                node_id=node_id,
                code=_CATALYST_ERROR,
                message=str(exc),
                failure=exc.failure,
            ),
            False,
        )
    except CollectionConflictError:
        return duplicate_failure(device, node_id, step_id=STEP_ID), False
    except TooManyRowsError as exc:
        code, message, failure = too_many_rows_failure(exc)
        return (
            failed_device(
                device,
                step_id=STEP_ID,
                node_id=node_id,
                code=code,
                message=message,
                failure=failure,
            ),
            False,
        )
    except (SQLAlchemyError, StorageRejected, ValueError) as exc:
        # ``ValueError`` also covers a client the mapper could not validate: not stored either.
        code, message, failure = storage_failure(exc)
        return (
            failed_device(
                device,
                step_id=STEP_ID,
                node_id=node_id,
                code=code,
                message=message,
                failure=failure,
            ),
            False,
        )
    except Exception as exc:
        # Not a controller or storage error (a bug, a parser error): fail this device only, the
        # same catch-all as ``collect-client-data`` (W8-01, W8-04).
        logger.warning("client data collection failed error=%s", type(exc).__name__)
        error = device_error_from_exception(exc, node_id=node_id, step_id=STEP_ID)
        return fail_device_with_error(device, error), False
    summary = {
        "source": "catalyst_center",
        "lookback_hours": lookback_hours,
        "arp_status": "ok",
        "mac_status": "ok",
        "arp_entries": len(ip_rows),
        "mac_entries": len(mac_rows),
    }
    return with_summary(device, node_id, summary), True


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions
    try:
        lookback_hours = parse_int_flag(
            config,
            "lookback_hours",
            default=DEFAULT_LOOKBACK_HOURS,
            minimum=1,
            maximum=MAX_LOOKBACK_HOURS,
        )
    except ValueError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc
    dry_run = parse_bool_flag(config, "dry_run")

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, STEP_ID)
    split = split_targets(context.devices, step_id=STEP_ID, node_id=node_id)
    credentials = resolve_source_credentials(db, list(split.by_source), step_id=STEP_ID)
    duplicates = find_duplicate_keys(
        (device_id, d.name) for device_id, d in context.devices.items()
    )

    logger.info(
        "%s started run_id=%s devices=%d lookback_hours=%d dry_run=%s",
        STEP_ID,
        log_run_id(run),
        len(context.devices),
        lookback_hours,
        dry_run,
    )

    store_lock = asyncio.Lock()
    gate = asyncio.Semaphore(MAX_PARALLEL_DEVICES)

    async def one(
        source_id: str, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        if device_id in duplicates:
            return device_id, duplicate_failure(device, node_id, step_id=STEP_ID), False
        result, ok = await _collect_one(
            device_id=device_id,
            device=device,
            node_id=node_id,
            session_id=run.uuid,
            lookback_hours=lookback_hours,
            dry_run=dry_run,
            credentials=credentials[source_id],
            store_lock=store_lock,
            gate=gate,
        )
        return device_id, result, ok

    results = await asyncio.gather(
        *(
            one(source_id, device_id, device)
            for source_id, devices in split.by_source.items()
            for device_id, device in devices.items()
        )
    )
    succeeded = {device_id: device for device_id, device, ok in results if ok}
    failed = {**split.rejected, **{i: d for i, d, ok in results if not ok}}
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        STEP_ID,
        len(succeeded),
        len(failed),
        log_run_id(run),
    )
    return build_outcomes(context, succeeded, failed)
