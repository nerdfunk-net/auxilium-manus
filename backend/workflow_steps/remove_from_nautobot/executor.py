"""Executor for the remove-from-nautobot step.

The device is identified by its Nautobot UUID only. With ``remove_ip_addresses`` the addresses
assigned to the device are deleted first, then the device. An address that is also assigned to
another device or VM is kept. All Nautobot work is done by the shared ``DeviceCommonService``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
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
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.common.update_field_expression import resolve_update_field_expression

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


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService


@dataclass(frozen=True)
class _Removal:
    bucket: str
    device: DeviceContext
    ips_removed: int = 0
    ips_shared_skipped: int = 0


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
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    client = CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
    return _Bound(DeviceCommonService(client))


def _config_failure() -> FailureInfo:
    return FailureInfo(phase="config", kind="bad_request", hint="check_request")


def _not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


def _ip_delete_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="server_error")


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


async def _remove_ips(
    common: DeviceCommonService, device_uuid: str
) -> tuple[list[str], int, str | None]:
    """Delete the addresses only this device holds.

    Returns (removed ids, number kept because another object holds them, failed ip id). The
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
            return removed, len(shared), ip_id
        removed.append(ip_id)
    return removed, len(shared), None


def _already_removed_note(removed: list[str]) -> str:
    """Sentence naming the addresses deleted before the step failed (empty when none)."""
    if not removed:
        return ""
    return f" {len(removed)} IP address(es) were already deleted: {', '.join(removed)}."


async def _remove(
    common: DeviceCommonService,
    parsed: _ParsedConfig,
    device: DeviceContext,
    node_id: str,
    run_id: str,
) -> _Removal:
    resolved = _resolve_device_uuid(parsed, device, run_id)
    if isinstance(resolved, tuple):
        code, message, failure = resolved
        return _failed(device, node_id=node_id, code=code, message=message, failure=failure)
    device_uuid = resolved

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
        if parsed.remove_ip_addresses:
            removed, skipped, failed_ip = await _remove_ips(common, device_uuid)
            if failed_ip is not None:
                return _failed(
                    device,
                    node_id=node_id,
                    code="ip_delete_failed",
                    message=(
                        f"IP address {failed_ip} could not be removed; the device was not removed."
                        f"{_already_removed_note(removed)}"
                    ),
                    failure=_ip_delete_failure(),
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
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        if removed:
            error = error.model_copy(
                update={
                    "code": "device_delete_failed",
                    "message": f"The device could not be removed.{_already_removed_note(removed)}",
                }
            )
        return _Removal("failure", fail_device_with_error(device, error), len(removed), skipped)
    return _Removal("success", device, len(removed), skipped)


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
    ips_removed: int,
    ips_shared_skipped: int,
) -> list[StepOutcome]:
    counts = {
        "devices_removed": len(buckets["success"]),
        "ips_removed": ips_removed,
        "ips_shared_skipped": ips_shared_skipped,
        "failed": len(buckets["failure"]),
    }
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
            context=context, node_id=node_id, buckets=buckets, ips_removed=0, ips_shared_skipped=0
        )

    common = _bind_nautobot(run, parsed.source_id).common
    logger.info(
        "remove-from-nautobot started run_id=%s node_id=%s devices=%d remove_ip_addresses=%s",
        context.run_id,
        node_id,
        len(context.devices),
        parsed.remove_ip_addresses,
    )

    # With address removal the devices go one after another: whether an address is shared is
    # decided from Nautobot's current state, so a device removed earlier in the run must already
    # be gone when the next one looks (otherwise two holders both keep it and it is orphaned).
    gate = asyncio.Semaphore(1 if parsed.remove_ip_addresses else _CONCURRENCY)

    async def run_one(device: DeviceContext) -> _Removal:
        async with gate:
            return await _remove(common, parsed, device, node_id, context.run_id)

    devices = list(context.devices.values())
    results = await asyncio.gather(*[run_one(device) for device in devices])
    ips_removed = ips_shared_skipped = 0
    for source, result in zip(devices, results, strict=True):
        buckets[result.bucket][source.id] = result.device
        ips_removed += result.ips_removed
        ips_shared_skipped += result.ips_shared_skipped

    logger.info(
        "remove-from-nautobot finished success=%d failure=%d ips_removed=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        ips_removed,
        context.run_id,
    )
    return _build_outcomes(
        context=context,
        node_id=node_id,
        buckets=buckets,
        ips_removed=ips_removed,
        ips_shared_skipped=ips_shared_skipped,
    )
