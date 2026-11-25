"""Executor for the remove-from-nautobot step.

The device is identified by its Nautobot UUID only. With ``remove_ip_addresses`` the addresses
assigned to the device are deleted first, then the device. An address that is also assigned to
another device or VM is kept. All Nautobot work is done by the shared ``DeviceCommonService``.

With ``dry_run`` nothing is deleted: the step reads the device (and, with
``remove_ip_addresses``, its addresses) and stores per device what it would remove in
``dry_run_results[<node id>]``. The preview reads Nautobot as it is now, so an address shared by
two devices of one run is reported as kept for both although the real run deletes it with the
last holder. Workflow devices that resolve to the same Nautobot UUID are removed once and share
the outcome.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotNotFoundError
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.devices.common import DeviceCommonService
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.nautobot_step import bind_nautobot_client
from workflow_steps.common.partial_outcomes import (
    NAUTOBOT_TEXT,
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.step_flags import parse_bool_flag, record_dry_run
from workflow_steps.common.value_expression import resolve_update_field_expression

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "remove-from-nautobot"
_OUTCOME_NAMES = ("success", "failure")
_CONCURRENCY = 5


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    device_id_expression: str
    remove_ip_addresses: bool
    dry_run: bool


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService


@dataclass(frozen=True)
class _Removal:
    bucket: str
    device: DeviceContext
    ips_removed: int = 0
    ips_shared_skipped: int = 0
    # Only a successful removal counts as one device removed (workflow devices that share a
    # Nautobot UUID are one removal).
    counted: bool = True


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    expression = str(config.get("device_id") or "").strip()
    if not expression:
        raise ValueError(f"{_STEP_ID}: device_id is not configured")
    return _ParsedConfig(
        source_id=source_id,
        device_id_expression=expression,
        remove_ip_addresses=parse_bool_flag(config, "remove_ip_addresses", default=False),
        dry_run=parse_bool_flag(config, "dry_run", default=False),
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    client = bind_nautobot_client(run, source_id, step_id=_STEP_ID)
    return _Bound(DeviceCommonService(client))


def _config_failure() -> FailureInfo:
    return FailureInfo(phase="config", kind="bad_request", hint="check_request")


def _not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


def _failed(
    device: DeviceContext,
    *,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo,
    ips_removed: int = 0,
    ips_shared_skipped: int = 0,
) -> _Removal:
    error = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return _Removal(
        "failure", fail_device_with_error(device, error), ips_removed, ips_shared_skipped
    )


def _resolve_device_uuid(
    parsed: _ParsedConfig, device: DeviceContext, run_id: str
) -> str | tuple[str, str, FailureInfo]:
    """The device UUID, or ``(code, message, failure)`` when it cannot be used."""
    # reveal_secrets=False and no echo of the value: it ends up in the stored error.
    value = resolve_update_field_expression(
        device=device,
        field_key="device_id",
        raw_value=parsed.device_id_expression,
        run_id=run_id,
        reveal_secrets=False,
    )
    config_failure = _config_failure()
    if value == REDACTED_PLACEHOLDER:
        return (
            "device_id_is_secret",
            "device_id expression points to a secret, which this step does not copy",
            config_failure,
        )
    if value is None or not value.strip():
        return "device_id_unresolved", "device_id expression resolved to nothing", config_failure
    device_uuid = value.strip()
    if not is_valid_uuid(device_uuid.lower()):
        return "device_id_invalid", "device_id is not a Nautobot UUID", config_failure
    return device_uuid


@dataclass(frozen=True)
class _IpDeleteFailure:
    ip_id: str
    error: Exception


async def _remove_ips(
    common: DeviceCommonService, device_uuid: str
) -> tuple[list[str], int, _IpDeleteFailure | None]:
    """Delete the addresses only this device holds.

    Returns (removed ids, number kept because another object holds them, the failed delete). The
    holders are looked up now, not planned earlier: devices of one run are processed one after
    another, so the last holder of a shared address sees it as exclusive and removes it.
    """
    owned, shared = await common.list_device_ip_ids(device_uuid)
    removed: list[str] = []
    for ip_id in owned:
        try:
            await common.delete_ip_address(ip_id)
        except NautobotNotFoundError:
            # Already gone (a retry): nothing left to remove.
            logger.debug("remove-from-nautobot ip=%s already removed", ip_id)
            continue
        except Exception as exc:
            logger.warning(
                "remove-from-nautobot could not delete ip=%s error=%s", ip_id, type(exc).__name__
            )
            return removed, len(shared), _IpDeleteFailure(ip_id, exc)
        removed.append(ip_id)
    return removed, len(shared), None


def _already_removed_note(removed: list[str]) -> str:
    """Sentence naming the addresses deleted before the step failed (empty when none)."""
    if not removed:
        return ""
    return f" {len(removed)} IP address(es) were already deleted: {', '.join(removed)}."


async def _preview(
    common: DeviceCommonService,
    parsed: _ParsedConfig,
    device: DeviceContext,
    node_id: str,
    device_uuid: str,
) -> _Removal:
    """What the removal would delete; nothing is written."""
    owned: list[str] = []
    shared: list[str] = []
    if parsed.remove_ip_addresses:
        owned, shared = await common.list_device_ip_ids(device_uuid)
    payload = {
        "would_remove_device": device_uuid,
        "would_remove_ips": list(owned),
        "would_keep_shared": len(shared),
    }
    return _Removal(
        "success", record_dry_run(device, node_id=node_id, payload=payload), len(owned), len(shared)
    )


async def _remove(
    common: DeviceCommonService,
    parsed: _ParsedConfig,
    device: DeviceContext,
    node_id: str,
    device_uuid: str,
) -> _Removal:
    removed: list[str] = []
    skipped = 0
    try:
        try:
            await common.get_device_details(device_uuid)
        except NautobotNotFoundError:
            return _failed(
                device,
                node_id=node_id,
                code="device_not_found",
                message="The device was not found in Nautobot; nothing was removed",
                failure=_not_found_failure(),
            )
        if parsed.dry_run:
            return await _preview(common, parsed, device, node_id, device_uuid)
        if parsed.remove_ip_addresses:
            removed, skipped, ip_failure = await _remove_ips(common, device_uuid)
            if ip_failure is not None:
                # The class of the error says what to do: a 403 is a token problem, a 409 a
                # protected address, a 5xx may be retried.
                classified = device_error_from_exception(
                    ip_failure.error, node_id=node_id, step_id=_STEP_ID, keep_text=NAUTOBOT_TEXT
                )
                return _failed(
                    device,
                    node_id=node_id,
                    code="ip_delete_failed",
                    message=(
                        f"IP address {ip_failure.ip_id} could not be removed; the device was not "
                        f"removed.{_already_removed_note(removed)}"
                    ),
                    failure=classified.failure or FailureInfo(phase="api", kind="server_error"),
                    ips_removed=len(removed),
                    ips_shared_skipped=skipped,
                )
        await common.delete_device(device_uuid)
    except NautobotNotFoundError:
        # Another worker removed the device between the check and the delete.
        return _failed(
            device,
            node_id=node_id,
            code="device_not_found",
            message=(
                f"The device was already gone when it was deleted.{_already_removed_note(removed)}"
            ),
            failure=_not_found_failure(),
            ips_removed=len(removed),
            ips_shared_skipped=skipped,
        )
    except Exception as exc:
        # Nautobot cannot delete a device and its addresses atomically: addresses removed
        # earlier stay removed. The device fails and the message lists them for the operator.
        error = device_error_from_exception(
            exc, node_id=node_id, step_id=_STEP_ID, keep_text=NAUTOBOT_TEXT
        )
        if removed:
            error = error.model_copy(
                update={
                    "code": "device_delete_failed",
                    "message": f"The device could not be removed.{_already_removed_note(removed)}",
                }
            )
        return _Removal("failure", fail_device_with_error(device, error), len(removed), skipped)
    return _Removal("success", device, len(removed), skipped)


def _shared_outcome(lead: _Removal, follower: DeviceContext, node_id: str) -> _Removal:
    """The outcome of a workflow device that resolved to the Nautobot device ``lead`` handled."""
    if lead.bucket == "success":
        preview = lead.device.dry_run_results.get(node_id)
        device = follower if preview is None else record_dry_run(
            follower, node_id=node_id, payload=preview
        )
        return _Removal("success", device, counted=False)
    return _Removal(
        "failure", fail_device_with_error(follower, lead.device.errors[-1]), counted=False
    )


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
    removals: list[_Removal],
    dry_run: bool,
) -> list[StepOutcome]:
    removed = sum(1 for r in removals if r.bucket == "success" and r.counted)
    ips = sum(r.ips_removed for r in removals)
    counts = {
        "dry_run": dry_run,
        "devices_removed": 0 if dry_run else removed,
        "ips_removed": 0 if dry_run else ips,
        "ips_shared_skipped": sum(r.ips_shared_skipped for r in removals),
        "failed": len(buckets["failure"]),
    }
    if dry_run:
        counts["devices_would_remove"] = removed
        counts["ips_would_remove"] = ips
    metadata = {**context.metadata, f"{node_id}.remove_counts": counts}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]


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

    parsed = _parse_config(config)
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    if not context.devices:
        return _build_outcomes(
            context=context, node_id=node_id, buckets=buckets, removals=[], dry_run=parsed.dry_run
        )

    common = _bind_nautobot(run, parsed.source_id).common
    logger.info(
        "remove-from-nautobot started run_id=%s node_id=%s devices=%d remove_ip_addresses=%s "
        "dry_run=%s",
        context.run_id,
        node_id,
        len(context.devices),
        parsed.remove_ip_addresses,
        parsed.dry_run,
    )

    removals: list[_Removal] = []
    # Workflow devices that name the same Nautobot device are one removal: the first one is
    # handled, the others take its outcome (a second delete would report "not found").
    by_uuid: dict[str, list[DeviceContext]] = {}
    for device in context.devices.values():
        resolved = _resolve_device_uuid(parsed, device, context.run_id)
        if isinstance(resolved, tuple):
            code, message, failure = resolved
            removal = _failed(device, node_id=node_id, code=code, message=message, failure=failure)
            buckets["failure"][device.id] = removal.device
            removals.append(removal)
        else:
            by_uuid.setdefault(resolved.lower(), []).append(device)

    # With address removal the devices go one after another: whether an address is shared is
    # decided from Nautobot's current state, so a device removed earlier in the run must already
    # be gone when the next one looks (otherwise two holders both keep it and it is orphaned).
    gate = asyncio.Semaphore(1 if parsed.remove_ip_addresses else _CONCURRENCY)

    async def run_one(device_uuid: str, device: DeviceContext) -> _Removal:
        async with gate:
            return await _remove(common, parsed, device, node_id, device_uuid)

    groups = list(by_uuid.items())
    leads = await asyncio.gather(*[run_one(uuid, devices[0]) for uuid, devices in groups])
    for (_uuid, devices), lead in zip(groups, leads, strict=True):
        outcomes = [lead, *(_shared_outcome(lead, other, node_id) for other in devices[1:])]
        for source, result in zip(devices, outcomes, strict=True):
            buckets[result.bucket][source.id] = result.device
            removals.append(result)

    logger.info(
        "remove-from-nautobot finished success=%d failure=%d ips_removed=%d dry_run=%s "
        "run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        sum(r.ips_removed for r in removals),
        parsed.dry_run,
        context.run_id,
    )
    return _build_outcomes(
        context=context,
        node_id=node_id,
        buckets=buckets,
        removals=removals,
        dry_run=parsed.dry_run,
    )
