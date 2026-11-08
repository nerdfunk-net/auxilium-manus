"""Executor for the collect-client-data step.

Connects to every device, reads its ARP table (default VRF and each VRF) and MAC address
table, optionally resolves the ARP addresses to hostnames, and stores the result in the
client data tables (one collection per device and run, see ``ClientDataCollection``).
Devices are keyed by name: two devices with one name in a step fail the second.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import object_session

from core.config import settings
from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.client_data import ClientHostnameRow, CollectionConflictError, TooManyRowsError
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.client_data.client_data_service import ClientDataService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from services.workflow_context.node_result import set_node_result
from workflow_steps.collect_client_data.collector import (
    CollectionError,
    DeviceCollection,
    DeviceTarget,
    collect_from_device,
    phase_one_commands,
)
from workflow_steps.collect_client_data.commands import SUPPORTED_DEVICE_TYPES
from workflow_steps.collect_client_data.dns import HostnameResolver, reverse_lookup
from workflow_steps.collect_client_data.options import STEP_ID, CollectOptions, parse_options
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.duplicate_keys import (
    DUPLICATE_KEY_CODE,
    DUPLICATE_KEY_FAILURE,
    find_duplicate_keys,
)
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
    mark_device_failed,
)
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.step_flags import record_dry_run

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_RESULT_KEY = "client_data"
_UNSUPPORTED_PLATFORM = FailureInfo(
    phase="connect", kind="unsupported_platform", hint="check_platform"
)


def _store_sync(
    *,
    session_id: str,
    device_name: str,
    device_ip: str | None,
    collection: DeviceCollection,
    hostnames: list[ClientHostnameRow],
    collected_at: datetime,
    target_host: str,
) -> None:
    db = get_db_session()
    try:
        ClientDataService(db).store_device_collection(
            session_id=session_id,
            device_name=device_name,
            device_ip=device_ip,
            ip_rows=collection.ip_rows,
            mac_rows=collection.mac_rows,
            hostname_rows=hostnames,
            status=collection.status,
            keep_sessions=settings.client_data_keep_sessions,
            collected_at=collected_at,
            target_host=target_host,
        )
    finally:
        db.close()


def _ip_or_none(host: str) -> str | None:
    """``device_ip`` is a 45-character address column: a hostname target is not stored there."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _summary(collection: DeviceCollection, hostname_count: int) -> dict[str, Any]:
    status = collection.status
    return {
        "arp_status": status.arp_status,
        "mac_status": status.mac_status,
        "vrf_status": status.vrf_status,
        "arp_entries": len(collection.ip_rows),
        "mac_entries": len(collection.mac_rows),
        "hostnames": hostname_count,
        "vrfs": list(collection.vrfs),
        # None = VRFs were not discovered (switched off or refused), which is not "no VRFs".
        "vrf_results": (
            None if status.vrfs is None else [result.model_dump() for result in status.vrfs]
        ),
    }


def _with_summary(device: DeviceContext, node_id: str, summary: dict[str, Any]) -> DeviceContext:
    """Write the summary under ``parsed.<node id>.client_data`` and stamp ``PARSED``.

    The registry promises ``produces: [parsed]``; the runner checks the capability on every
    device of the success outcome.
    """
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "parsed": set_node_result(device.parsed, node_id, _RESULT_KEY, summary),
            "capabilities": device.capabilities | {Capability.PARSED},
        }
    )


def _fail(
    device: DeviceContext,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> DeviceContext:
    return mark_device_failed(
        device, node_id=node_id, step_id=STEP_ID, code=code, message=message, failure=failure
    )


def _target(
    device: DeviceContext, options: CollectOptions, credentials: tuple[str, str, str]
) -> DeviceTarget:
    """Resolve the SSH target; raises ``CollectionError`` when the device cannot be reached."""
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        raise CollectionError("missing_host", f"Device {device.id} has no hostname or primary IP")
    try:
        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=options.network_driver_override,
        )
    except ValueError as exc:  # UnsupportedPlatformError
        raise CollectionError(
            "unsupported_platform", str(exc), failure_from_exception(exc) or _UNSUPPORTED_PLATFORM
        ) from exc
    if device_type not in SUPPORTED_DEVICE_TYPES:
        raise CollectionError(
            "unsupported_platform",
            "Client data can be collected from Cisco IOS, IOS-XE and NX-OS devices only",
            _UNSUPPORTED_PLATFORM,
        )
    username, password, reference = credentials
    return DeviceTarget(
        host=host,
        device_type=device_type,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        credential_reference=reference,
    )


async def _hostnames(
    resolver: HostnameResolver | None, collection: DeviceCollection
) -> list[ClientHostnameRow]:
    if resolver is None:
        return []
    names = await resolver.resolve({row.ip_address for row in collection.ip_rows})
    return [ClientHostnameRow(ip_address=ip, hostname=name) for ip, name in sorted(names.items())]


async def _collect_one(
    *,
    device: DeviceContext,
    node_id: str,
    session_id: str,
    options: CollectOptions,
    credentials: tuple[str, str, str],
    netmiko: NetmikoService,
    resolver: HostnameResolver | None,
    store_lock: asyncio.Lock,
) -> tuple[DeviceContext, bool]:
    try:
        target = _target(device, options, credentials)
        if options.dry_run:
            payload = {
                "would_collect": True,
                "host": target.host,
                "commands": phase_one_commands(options),
                "collect_hostname": options.collect_hostname,
            }
            previewed = record_dry_run(device, node_id=node_id, payload=payload)
            return _with_summary(previewed, node_id, {"dry_run": True}), True
        # Stamped when collection starts, not after DNS and queueing for the write lock: the
        # per-device ranking (and the keep-N pruning) must order collections by when they ran.
        collected_at = datetime.now(UTC)
        collection = await collect_from_device(
            netmiko=netmiko,
            target=target,
            options=options,
            max_rows=settings.client_data_max_rows_per_table,
        )
        hostnames = await _hostnames(resolver, collection)
        # One write at a time: each is short, and a large fan-out must not take a pooled
        # database connection per device.
        async with store_lock:
            await asyncio.to_thread(
                _store_sync,
                session_id=session_id,
                device_name=device.name,
                device_ip=_ip_or_none(target.host),
                collection=collection,
                hostnames=hostnames,
                collected_at=collected_at,
                target_host=target.host,
            )
    except CollectionError as exc:
        return _fail(device, node_id, exc.code, exc.message, exc.failure), False
    except CollectionConflictError:
        # Another execution (a fan-out sibling) stored a different device with this name.
        return _duplicate_failure(device, node_id), False
    except TooManyRowsError as exc:
        # The storage layer's own check (the collector normally catches this first).
        return _fail(
            device,
            node_id,
            "too_many_rows",
            f"The {exc.table} table has more rows than CLIENT_DATA_MAX_ROWS_PER_TABLE "
            f"({exc.limit}) allows; nothing was stored for this device",
            FailureInfo(phase="command", kind="payload_too_large"),
        ), False
    except (SQLAlchemyError, ValueError) as exc:
        # Database text can carry SQL and bound values: keep the class name only.
        logger.warning("client data storage failed error=%s", type(exc).__name__)
        message = "The collected data could not be stored"
        failure = FailureInfo(
            phase="internal", kind="internal_error", exception_type=type(exc).__name__
        )
        return _fail(device, node_id, "storage_failed", message, failure), False
    except Exception as exc:
        # Reduced to a closed vocabulary: library messages can carry host, banner or SQL text.
        error = device_error_from_exception(exc, node_id=node_id, step_id=STEP_ID)
        return fail_device_with_error(device, error), False
    summary = _summary(collection, len(hostnames))
    return _with_summary(device, node_id, summary), True


def _duplicate_failure(device: DeviceContext, node_id: str) -> DeviceContext:
    return _fail(
        device,
        node_id,
        DUPLICATE_KEY_CODE,
        f"another device in this run has the same name as {device.name!r} (in this step or "
        "in another execution); client data is stored per device name",
        DUPLICATE_KEY_FAILURE,
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    options = parse_options(config)
    reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    db = object_session(run)
    if db is None:
        raise RuntimeError("collect-client-data: WorkflowRun has no active DB session")
    username, password = resolve_ssh_credential(db, reference, acting_user_id=run.triggered_by_id)
    credentials = (username, password, reference)
    netmiko = NetmikoService(pool=device_sessions)
    duplicates = find_duplicate_keys(
        (device_id, d.name) for device_id, d in context.devices.items()
    )

    logger.info(
        "collect-client-data run_id=%s devices=%d ip=%s mac=%s vrfs=%s hostnames=%s dry_run=%s",
        run.id,
        len(context.devices),
        options.collect_ip_address,
        options.collect_mac_address,
        options.collect_vrfs,
        options.collect_hostname,
        options.dry_run,
    )

    store_lock = asyncio.Lock()
    async with AsyncExitStack() as stack:
        resolver = (
            await stack.enter_async_context(
                HostnameResolver(
                    timeout=options.dns_timeout_seconds,
                    concurrency=options.dns_concurrency,
                    lookup=reverse_lookup,
                )
            )
            if options.collect_hostname
            else None
        )

        async def one(device_id: str, device: DeviceContext) -> tuple[str, DeviceContext, bool]:
            if device_id in duplicates:
                return device_id, _duplicate_failure(device, node_id), False
            result, ok = await _collect_one(
                device=device,
                node_id=node_id,
                session_id=run.uuid,
                options=options,
                credentials=credentials,
                netmiko=netmiko,
                resolver=resolver,
                store_lock=store_lock,
            )
            return device_id, result, ok

        results = await asyncio.gather(*(one(i, d) for i, d in context.devices.items()))

    success = {device_id: device for device_id, device, ok in results if ok}
    failed = {device_id: device for device_id, device, ok in results if not ok}
    logger.info(
        "collect-client-data finished success=%d failure=%d run_id=%s",
        len(success),
        len(failed),
        run.id,
    )
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success}),
            summary=f"collected client data from {len(success)} device(s)",
        )
    ]
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed}),
                summary=f"{len(failed)} device(s) failed",
            )
        )
    return outcomes
