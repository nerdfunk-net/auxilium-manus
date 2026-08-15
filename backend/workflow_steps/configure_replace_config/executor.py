"""Executor for the configure-replace-config step.

Applies a configuration file already present on a device (e.g. uploaded by
an upstream Upload Config step) via Cisco's ``configure replace <file> force
time <n>``, which schedules an automatic on-device rollback after ``n``
minutes unless ``configure confirm`` is sent first. This step never imports
pyats/genie directly -- see "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md. Device connection info and credentials come entirely
from the ``pyats_testbed`` bag written by an upstream add-pyats-testbed
step; this step resolves no credentials of its own.

No pyATS shim changes are needed: the flow is composed entirely from the
``operation="execute"`` shim call, sending the replace command and then the
confirm command. Each shim call is its own fresh connect/disconnect -- there
is no need to hold one session open across the whole flow, because the
rollback timer is device-side, not tied to the CLI session that issued it.

Verification is deliberately simple: send ``configure replace``, then
immediately send ``configure confirm`` and inspect its output rather than
diffing Genie snapshots before/after (interface counters and other benign
noise made snapshot diffs unreliable in practice, flagging clean replaces as
failed). Reconnecting to send ``configure confirm`` doubles as the
connectivity check -- if the replace broke reachability, that shim call
fails outright. If the device responds with "No Rollback Confirmed Change
pending" (e.g. the timer already expired, or another session already
confirmed it), the outcome is reported as a step failure rather than
silently swallowed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from services.workflow_context.secret_fields import unwrap_secret
from workflow_steps.configure_replace_config.config import get_config

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "configure-replace-config"
_CONFIRM_COMMAND = "configure confirm"
_MIN_TIMEOUT_MINUTES = 1
_MAX_TIMEOUT_MINUTES = 120
_ARCHIVE_NOT_CONFIGURED_MARKER = "turn config archive on"
_NO_PENDING_ROLLBACK_MARKER = "no rollback confirmed change pending"


def _is_archive_not_configured_error(message: str | None) -> bool:
    """True when the device rejected 'configure replace ... time N' because
    config archiving (required by the 'Rollback Confirmed Change' feature)
    is not set up -- e.g. Cisco IOS's '%Turn config archive on before using
    Rollback Confirmed Change'.
    """
    return _ARCHIVE_NOT_CONFIGURED_MARKER in (message or "").lower()


def _has_no_pending_rollback(raw_output: Any) -> bool:
    """True when 'configure confirm' reports no pending timed change --
    e.g. Cisco IOS's '%No Rollback Confirmed Change pending'. This means the
    timer already expired (device reverted) or another session already
    confirmed it; either way this run can't vouch for the outcome.
    """
    return _NO_PENDING_ROLLBACK_MARKER in str(raw_output or "").lower()


def _resolve_source_credentials(
    db: Session, source_ids: set[str]
) -> tuple[dict[str, PyATSCredentials], dict[str, str]]:
    """Resolve every distinct pyats_source_id once. Returns (credentials_by_id, error_by_id)."""
    config_service = PyATSSourceConfigService(db)
    credentials: dict[str, PyATSCredentials] = {}
    errors: dict[str, str] = {}
    for source_id in source_ids:
        try:
            credentials[source_id] = config_service.resolve_credentials(source_id)
        except (PyATSSourceNotFoundError, PyATSValidationError) as exc:
            errors[source_id] = str(exc)
    return credentials, errors


def _fail_device(
    *, device: DeviceContext, device_id: str, node_id: str, code: str, message: str
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_id, failed, False


async def _call_shim(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    command: str,
) -> tuple[bool, Any, str | None]:
    """Run a single-command shim job. Returns (ok, value, error_message)."""
    try:
        response = await shim.run_job(
            shim_credentials,
            operation=operation,
            devices=[shim_device],
            commands=[command],
        )
    except PyATSAPIError as exc:
        return False, None, str(exc)

    result = (response.get("results") or {}).get(shim_device["name"])
    if not result or not result.get("success", False):
        message = (result or {}).get("error") or "pyATS shim reported failure for this device"
        return False, None, message

    entry = (result.get("commands") or {}).get(command) or {}
    if entry.get("error"):
        return False, None, entry["error"]

    value = entry.get("parsed") if operation == "learn" else entry.get("raw")
    return True, value, None


async def _process_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    destination_filename: str,
    file_system: str,
    timeout_minutes: int,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
) -> tuple[str, DeviceContext, bool]:
    bag = device.attribute_bags.get("pyats_testbed")
    if not isinstance(bag, dict):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_testbed",
            message="No pyats_testbed bag found -- add an Add Testbed step upstream",
        )

    source_id = str(bag.get("pyats_source_id") or "")
    if source_id in source_errors:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=source_errors[source_id],
        )
    shim_credentials = source_credentials.get(source_id)
    if shim_credentials is None:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=f"pyATS source {source_id!r} could not be resolved",
        )

    password = unwrap_secret(bag.get("password"))
    if not password:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_credential",
            message="pyats_testbed bag has no usable password",
        )

    shim_device = {
        "name": device_id,
        "host": bag.get("host"),
        "os": bag.get("os"),
        "username": bag.get("username"),
        "password": password,
    }

    shim = service_factory.get_pyats_app_service()

    logger.info(
        "%s replace starting device=%s host=%s os=%s source=%s",
        _STEP_ID,
        device_id,
        bag.get("host"),
        bag.get("os"),
        source_id,
    )

    replace_command = (
        f"configure replace {file_system}{destination_filename} force time {timeout_minutes}"
    )
    logger.info(
        "%s replace device=%s host=%s command=%s",
        _STEP_ID,
        device_id,
        bag.get("host"),
        replace_command,
    )
    started = time.monotonic()
    ok, _, err = await _call_shim(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        command=replace_command,
    )
    if not ok:
        if _is_archive_not_configured_error(err):
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="archive_not_configured",
                message=(
                    "Device rejected 'configure replace' because config archiving is not "
                    "enabled -- the 'time'/Rollback Confirmed Change feature this step relies "
                    "on requires it. Configure it once on the device, e.g.:\n"
                    "  archive\n"
                    "   path flash:archive\n"
                    "then retry. See this step's Help panel for details."
                ),
            )
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="replace_failed",
            message=f"'configure replace' failed or the connection was lost: {err}",
        )
    logger.info(
        "%s replace returned device=%s host=%s elapsed=%.1fs",
        _STEP_ID,
        device_id,
        bag.get("host"),
        time.monotonic() - started,
    )

    ok, confirm_raw, err = await _call_shim(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        command=_CONFIRM_COMMAND,
    )
    if not ok:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="confirm_failed",
            message=(
                f"Could not reconnect/send '{_CONFIRM_COMMAND}' after 'configure replace' "
                f"({err}); device will auto-revert after {timeout_minutes} minute(s)"
            ),
        )

    if _has_no_pending_rollback(confirm_raw):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="confirm_not_pending",
            message=(
                f"Device reported no pending Rollback Confirmed Change when "
                f"'{_CONFIRM_COMMAND}' was sent -- the timed replace may have already reverted "
                f"or been confirmed by another session; verify the running configuration "
                f"manually"
            ),
        )

    entry = {
        "kind": "configure_replace",
        "confirmed": True,
        "destination_filename": destination_filename,
        "file_system": file_system,
        "timeout_minutes": timeout_minutes,
    }
    parsed = dict(device.parsed)
    parsed[f"{node_id}.configure_replace"] = entry
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, True


def _partition(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        (success if ok else failed)[device_id] = updated_device
    return success, failed


def _parse_timeout_minutes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{_STEP_ID}: timeout_minutes must be an integer")
    if not (_MIN_TIMEOUT_MINUTES <= value <= _MAX_TIMEOUT_MINUTES):
        raise ValueError(
            f"{_STEP_ID}: timeout_minutes must be between {_MIN_TIMEOUT_MINUTES} and "
            f"{_MAX_TIMEOUT_MINUTES}"
        )
    return value


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: pyATS connects via the shim, not Netmiko
    del artifact_service  # unused: verification no longer stores a diff artifact

    merged_config = {**get_config(), **config}

    destination_filename = str(merged_config.get("destination_filename") or "").strip()
    if not destination_filename:
        raise ValueError(f"{_STEP_ID}: destination_filename is required")
    file_system = str(merged_config.get("file_system") or "").strip()
    if not file_system:
        raise ValueError(f"{_STEP_ID}: file_system is required")
    timeout_minutes = _parse_timeout_minutes(merged_config.get("timeout_minutes"))

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d destination_filename=%s file_system=%s "
        "timeout_minutes=%d",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        destination_filename,
        file_system,
        timeout_minutes,
    )

    source_ids = {
        str(device.attribute_bags["pyats_testbed"]["pyats_source_id"])
        for device in context.devices.values()
        if isinstance(device.attribute_bags.get("pyats_testbed"), dict)
        and device.attribute_bags["pyats_testbed"].get("pyats_source_id")
    }
    source_credentials, source_errors = _resolve_source_credentials(db, source_ids)

    results = await asyncio.gather(
        *[
            _process_one_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                destination_filename=destination_filename,
                file_system=file_system,
                timeout_minutes=timeout_minutes,
                source_credentials=source_credentials,
                source_errors=source_errors,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition(results)

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure", context=context.model_copy(update={"devices": failed_devices})
            )
        )
    return outcomes
