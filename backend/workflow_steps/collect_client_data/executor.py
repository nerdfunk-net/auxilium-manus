"""Executor for the collect-client-data step.

Connects to every device, reads its ARP table (default VRF and each VRF) and MAC address
table, optionally resolves the ARP addresses to hostnames, and stores the result in the
client data tables (one collection per device and run, see ``ClientDataCollection``).
Devices are keyed by name: two devices with one name in a step fail the second.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from core.config import settings
from core.models.runs import WorkflowRun
from models.client_data import ClientHostnameRow, CollectionConflictError, TooManyRowsError
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.service import NetmikoService
from workflow_steps.collect_client_data.collector import (
    CollectionError,
    DeviceCollection,
    DeviceTarget,
    collect_from_device,
    phase_one_commands,
    too_many_rows_error,
)
from workflow_steps.collect_client_data.commands import SUPPORTED_DEVICE_TYPES
from workflow_steps.collect_client_data.dns import HostnameResolver, reverse_lookup
from workflow_steps.collect_client_data.options import STEP_ID, CollectOptions, parse_options
from workflow_steps.common.client_data_store import (
    StorageRejected,
    duplicate_failure,
    ip_or_none,
    storage_failure,
    store_collection,
    with_summary,
)
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_type import connection_device_type
from workflow_steps.common.duplicate_keys import (
    find_duplicate_keys,
)
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
    mark_device_failed,
)
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import record_dry_run

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_UNSUPPORTED_PLATFORM = FailureInfo(
    phase="connect", kind="unsupported_platform", hint="check_platform"
)


def _summary(collection: DeviceCollection, hostname_count: int) -> dict[str, Any]:
    status = collection.status
    return {
        "arp_status": status.arp_status,
        "mac_status": status.mac_status,
        "vrf_status": status.vrf_status,
        "neighbor_status": status.neighbor_status,
        "neighbor_entries": len(collection.neighbor_rows),
        "arp_entries": len(collection.ip_rows),
        "mac_entries": len(collection.mac_rows),
        "hostnames": hostname_count,
        "vrfs": list(collection.vrfs),
        # None = VRFs were not discovered (switched off or refused), which is not "no VRFs".
        "vrf_results": (
            None if status.vrfs is None else [result.model_dump() for result in status.vrfs]
        ),
    }


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
        raise CollectionError(
            "missing_host", f"Device {device.id} has no hostname or primary IP", INVALID_INPUT
        )
    try:
        device_type = connection_device_type(device, options.network_driver_override)
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
                "commands": phase_one_commands(options, target.device_type),
                "collect_hostname": options.collect_hostname,
            }
            previewed = record_dry_run(device, node_id=node_id, payload=payload)
            return with_summary(previewed, node_id, {"dry_run": True}), True
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
        await store_collection(
            store_lock,
            session_id=session_id,
            device_name=device.name,
            device_ip=ip_or_none(target.host),
            ip_rows=collection.ip_rows,
            mac_rows=collection.mac_rows,
            hostname_rows=hostnames,
            status=collection.status,
            neighbor_rows=collection.neighbor_rows,
            collected_at=collected_at,
            target_host=target.host,
        )
    except CollectionError as exc:
        return _fail(device, node_id, exc.code, exc.message, exc.failure), False
    except CollectionConflictError:
        # Another execution (a fan-out sibling) stored a different device with this name.
        return duplicate_failure(device, node_id, step_id=STEP_ID), False
    except TooManyRowsError as exc:
        # The storage layer's own check (the collector normally catches this first).
        failed = too_many_rows_error(exc)
        return _fail(device, node_id, failed.code, failed.message, failed.failure), False
    except (SQLAlchemyError, StorageRejected) as exc:
        code, message, failure = storage_failure(exc)
        return _fail(device, node_id, code, message, failure), False
    except Exception as exc:
        # Reduced to a closed vocabulary: library messages can carry host, banner or SQL text.
        error = device_error_from_exception(exc, node_id=node_id, step_id=STEP_ID)
        return fail_device_with_error(device, error), False
    summary = _summary(collection, len(hostnames))
    return with_summary(device, node_id, summary), True


async def _collect_or_duplicate(
    device_id: str,
    device: DeviceContext,
    *,
    duplicates: Mapping[str, str],
    **collect: Any,
) -> tuple[str, DeviceContext, bool]:
    """One device of the fan-out: a duplicate name fails without a login, the rest is collected."""
    if device_id in duplicates:
        return device_id, duplicate_failure(device, collect["node_id"], step_id=STEP_ID), False
    result, ok = await _collect_one(device=device, **collect)
    return device_id, result, ok


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
    options = parse_options(config)
    reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, "collect-client-data")
    username, password = resolve_ssh_credential(db, reference, acting_user_id=run.triggered_by_id)
    credentials = (username, password, reference)
    netmiko = NetmikoService(pool=device_sessions)
    duplicates = find_duplicate_keys(
        (device_id, d.name) for device_id, d in context.devices.items()
    )

    logger.info(
        "collect-client-data run_id=%s devices=%d ip=%s mac=%s vrfs=%s hostnames=%s dry_run=%s",
        log_run_id(run),
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

        results = await asyncio.gather(
            *(
                _collect_or_duplicate(
                    device_id,
                    device,
                    duplicates=duplicates,
                    node_id=node_id,
                    session_id=run.uuid,
                    options=options,
                    credentials=credentials,
                    netmiko=netmiko,
                    resolver=resolver,
                    store_lock=store_lock,
                )
                for device_id, device in context.devices.items()
            )
        )

    success = {device_id: device for device_id, device, ok in results if ok}
    failed = {device_id: device for device_id, device, ok in results if not ok}
    logger.info(
        "collect-client-data finished success=%d failure=%d run_id=%s",
        len(success),
        len(failed),
        log_run_id(run),
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
