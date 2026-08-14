"""Executor for the configure-replace-config step.

Applies a configuration file already present on a device (e.g. uploaded by
an upstream Upload Config step) via Cisco's ``configure replace <file> time
<n> force``, which schedules an automatic on-device rollback after ``n``
minutes unless ``configure confirm`` is sent first. This step never imports
pyats/genie directly -- see "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md. Device connection info and credentials come entirely
from the ``pyats_testbed`` bag written by an upstream add-pyats-testbed
step; this step resolves no credentials of its own.

No pyATS shim changes are needed: the flow is composed entirely from shim
capabilities that already exist and are already used elsewhere --
``operation="learn"`` (same call get-pyats-snapshot uses) captures a Genie
``interface`` snapshot before and after the replace, ``POST /v1/diff``
(same endpoint compare-pyats-snapshot uses) diffs them, and
``operation="execute"`` sends both the replace and confirm CLI commands.
Each shim call is its own fresh connect/disconnect -- there is no need to
hold one session open across the whole flow, because the rollback timer is
device-side, not tied to the CLI session that issued it.

``configure confirm`` is deliberately withheld -- leaving the device to
auto-revert on its own timer -- whenever the post-change snapshot can't be
captured at all (the strongest signal the replace broke connectivity) or
when it differs from the pre-change baseline. Both cases are reported as a
step failure (see doc/WORKFLOW-STEPS.md's status semantics), not silently
swallowed.
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
_VERIFY_FEATURE = "interface"
_CONFIRM_COMMAND = "configure confirm"
_MIN_TIMEOUT_MINUTES = 1
_MAX_TIMEOUT_MINUTES = 120


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


async def _fail_with_diff(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    timeout_minutes: int,
    diff_text: str,
    context_run_id: str | None,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    diff_ref = await artifact_service.store(
        content=diff_text,
        kind="comparison_diff",
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    message = (
        f"Post-change {_VERIFY_FEATURE} snapshot differs from the baseline; "
        f"'{_CONFIRM_COMMAND}' was NOT sent -- device will auto-revert after "
        f"{timeout_minutes} minute(s)"
    )
    err = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code="verification_failed", message=message
    )
    parsed = dict(device.parsed)
    parsed[f"{node_id}.configure_replace"] = {
        "kind": "configure_replace",
        "confirmed": False,
        "diff_artifact_ref": diff_ref.model_dump(mode="json"),
        "timeout_minutes": timeout_minutes,
    }
    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
        }
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
    context_run_id: str | None,
    artifact_service: ArtifactService,
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
        "%s pre-snapshot device=%s host=%s os=%s source=%s",
        _STEP_ID,
        device_id,
        bag.get("host"),
        bag.get("os"),
        source_id,
    )
    ok, pre_data, err = await _call_shim(
        shim, shim_credentials, operation="learn", shim_device=shim_device, command=_VERIFY_FEATURE
    )
    if not ok:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="pre_snapshot_failed",
            message=f"Could not capture baseline {_VERIFY_FEATURE} snapshot: {err}",
        )

    replace_command = (
        f"configure replace {file_system}{destination_filename} time {timeout_minutes} force"
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

    ok, post_data, err = await _call_shim(
        shim, shim_credentials, operation="learn", shim_device=shim_device, command=_VERIFY_FEATURE
    )
    if not ok:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="post_snapshot_failed",
            message=(
                f"Could not reconnect/capture post-change {_VERIFY_FEATURE} snapshot after "
                f"'configure replace' ({err}); '{_CONFIRM_COMMAND}' was NOT sent -- device will "
                f"auto-revert after {timeout_minutes} minute(s)"
            ),
        )

    try:
        diff_response = await shim.diff(shim_credentials, snapshot_a=pre_data, snapshot_b=post_data)
    except (PyATSAPIError, PyATSValidationError) as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="diff_failed",
            message=(
                f"Could not verify configuration impact ({exc}); '{_CONFIRM_COMMAND}' was NOT sent "
                f"-- device will auto-revert after {timeout_minutes} minute(s)"
            ),
        )

    if not diff_response.get("identical"):
        return await _fail_with_diff(
            device=device,
            device_id=device_id,
            node_id=node_id,
            timeout_minutes=timeout_minutes,
            diff_text=str(diff_response.get("diff") or ""),
            context_run_id=context_run_id,
            artifact_service=artifact_service,
        )

    ok, _, err = await _call_shim(
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
                f"Verification passed but '{_CONFIRM_COMMAND}' failed ({err}); device may "
                f"auto-revert after {timeout_minutes} minute(s) unless confirmed another way"
            ),
        )

    entry = {
        "kind": "configure_replace",
        "confirmed": True,
        "destination_filename": destination_filename,
        "file_system": file_system,
        "timeout_minutes": timeout_minutes,
        "verify_feature": _VERIFY_FEATURE,
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
                context_run_id=context.run_id,
                artifact_service=artifact_service,
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
