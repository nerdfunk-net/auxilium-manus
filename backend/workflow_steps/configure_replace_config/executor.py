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
``operation="execute"`` shim call. The pre-check and post-check diffs are
each their own fresh connect/disconnect (they're read-only and order
doesn't matter), but ``configure replace ... time N`` and the following
``configure confirm`` are sent together as *one* shim job -- i.e. one
connect, both commands, one disconnect. This is deliberate, not an
optimization: in testing, sending ``configure confirm`` as a separate job
(a fresh reconnect) reliably got back "%No Rollback Confirmed Change
pending" even though the replace had genuinely applied and stuck -- the
device's Rollback Confirmed Change "pending" bookkeeping appears to be
scoped to the CLI session that issued the timed replace, not global to the
device. A brand-new session simply can't see it. Keeping both commands on
one connection sidesteps that entirely.

``configure confirm`` succeeding only proves the rollback timer was
cancelled -- it says nothing about whether every line of the target file
actually applied. Two optional device-native config diffs
(``show archive config differences system:running-config <file>``) bracket
the replace to close that gap:

* ``skip_if_no_pending_changes`` (pre-check): if the target file already
  matches the running config, skip ``configure replace``/``configure
  confirm`` entirely rather than cycling the device through a rollback
  timer for a no-op. A non-empty pre-diff is stored as an artifact for
  visibility but does not block the replace.
* ``verify_diff_after_replace`` (post-check): after ``configure confirm``
  succeeds, diff again. A non-empty diff means the running config still
  doesn't match the target despite the timer being cancelled, so the
  device is failed with the diff stored as an artifact.

This is a config-text diff (not a Genie/operational-state diff), so it
avoids the counter/timestamp noise that made an earlier Genie
before/after-snapshot approach unreliable (see git history). Both checks
fail open on a shim/command error (proceed with the replace unverified)
rather than blocking the run on a diagnostic command's failure -- except
the post-check, where a failed diff means we can no longer vouch for the
outcome and the device is failed.

The diff command always prints a ``!Contextual Config Diffs:`` header, even
when there is nothing to report -- IOS then follows it with
``!No changes were found`` rather than leaving the body blank. A plain
``.strip()`` truthiness check on that text would treat every call as a real
diff; ``_diff_has_changes`` filters both known no-op lines out first.

Sending ``configure confirm`` on the same connection means a broken-reachability
scenario no longer shows up as a failed reconnect; instead it shows up as
``configure confirm`` itself erroring on that still-open channel (connection
drop, timeout, etc.), which is handled the same way. ``verify_diff_after_replace``
(on by default) still opens a fresh connection afterward for the post-check
diff, so a device that's become unreachable to *new* connections is still
caught there. If the device responds with "No Rollback Confirmed Change
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
_DIFF_ARTIFACT_KIND_PRE = "configure_replace_pre_diff"
_DIFF_ARTIFACT_KIND_POST = "configure_replace_post_diff"


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


def _diff_has_changes(diff_text: str) -> bool:
    """True when a 'show archive config differences' response represents a
    real difference.

    The command always prints a '!Contextual Config Diffs:' header line, even
    when there is nothing to report -- Cisco IOS then follows it with
    '!No changes were found' rather than leaving the rest of the output
    blank. A plain truthiness/``.strip()`` check on the raw text therefore
    treats every call as a diff; this walks the non-blank lines and ignores
    only those two known no-op lines.
    """
    for line in diff_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lstrip("!").strip().lower()
        if lowered in ("contextual config diffs:", "no changes were found"):
            continue
        return True
    return False


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


def _fail_replace(
    *, device: DeviceContext, device_id: str, node_id: str, error: str | None
) -> tuple[str, DeviceContext, bool]:
    """Fail a device for a 'configure replace' error, whether it surfaced as a
    connection/job-level failure or as a per-command error on an otherwise-connected
    session -- both land here so the archive-not-configured hint stays in one place."""
    if _is_archive_not_configured_error(error):
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
        message=f"'configure replace' failed or the connection was lost: {error}",
    )


async def _run_shim_job(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    commands: list[str],
) -> tuple[bool, dict[str, dict[str, Any]], str | None]:
    """Run a shim job with one or more commands over a single device connection.

    The shim connects once, runs every command in ``commands`` against that
    same connection in order, then disconnects -- see generic_script.py's
    ``run_commands``. Returns (ok, command_entries, error_message); ``ok`` is
    False only when the connection/job itself failed for this device (each
    entry in ``command_entries`` -- keyed by command text -- can still carry
    its own per-command ``error`` even when ``ok`` is True).
    """
    try:
        response = await shim.run_job(
            shim_credentials,
            operation=operation,
            devices=[shim_device],
            commands=commands,
        )
    except PyATSAPIError as exc:
        return False, {}, str(exc)

    result = (response.get("results") or {}).get(shim_device["name"])
    if not result or not result.get("success", False):
        message = (result or {}).get("error") or "pyATS shim reported failure for this device"
        return False, {}, message

    return True, result.get("commands") or {}, None


async def _call_shim(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    command: str,
) -> tuple[bool, Any, str | None]:
    """Run a single-command shim job. Returns (ok, value, error_message)."""
    ok, command_entries, err = await _run_shim_job(
        shim, shim_credentials, operation=operation, shim_device=shim_device, commands=[command]
    )
    if not ok:
        return False, None, err

    entry = command_entries.get(command) or {}
    if entry.get("error"):
        return False, None, entry["error"]

    value = entry.get("parsed") if operation == "learn" else entry.get("raw")
    return True, value, None


def _build_diff_command(*, file_system: str, destination_filename: str) -> str:
    target = f"{file_system}{destination_filename}"
    return f"show archive config differences system:running-config {target}"


def _device_with_diff_refs(
    device: DeviceContext,
    node_id: str,
    *,
    pre_diff_artifact_ref: Any | None,
    post_diff_artifact_ref: Any | None,
) -> DeviceContext:
    """Record diff artifact refs on the device's parsed output, independent of
    whether the device ends up succeeding or failing."""
    if pre_diff_artifact_ref is None and post_diff_artifact_ref is None:
        return device
    entry: dict[str, Any] = {"kind": "configure_replace_diff"}
    if pre_diff_artifact_ref is not None:
        entry["pre_diff_artifact_ref"] = pre_diff_artifact_ref.model_dump(mode="json")
    if post_diff_artifact_ref is not None:
        entry["post_diff_artifact_ref"] = post_diff_artifact_ref.model_dump(mode="json")
    parsed = dict(device.parsed)
    parsed[f"{node_id}.configure_replace_diff"] = entry
    return device.model_copy(
        update={"parsed": parsed, "capabilities": device.capabilities | {Capability.PARSED}}
    )


async def _run_diff(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    shim_device: dict[str, Any],
    diff_command: str,
) -> tuple[bool, str, str | None]:
    """Run the config-text diff command. Returns (ok, diff_text, error_message)."""
    ok, raw, err = await _call_shim(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        command=diff_command,
    )
    if not ok:
        return False, "", err
    return True, str(raw or ""), None


async def _process_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    destination_filename: str,
    file_system: str,
    timeout_minutes: int,
    skip_if_no_pending_changes: bool,
    verify_diff_after_replace: bool,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
    artifact_service: ArtifactService,
    context_run_id: str,
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

    diff_command = _build_diff_command(
        file_system=file_system, destination_filename=destination_filename
    )
    pre_diff_artifact_ref = None
    if skip_if_no_pending_changes:
        diff_ok, pre_diff_text, diff_err = await _run_diff(
            shim, shim_credentials, shim_device=shim_device, diff_command=diff_command
        )
        if diff_ok and not _diff_has_changes(pre_diff_text):
            entry = {
                "kind": "configure_replace",
                "confirmed": False,
                "skipped": True,
                "reason": "no_pending_changes",
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
            logger.info(
                "%s skipped device=%s host=%s reason=no_pending_changes",
                _STEP_ID,
                device_id,
                bag.get("host"),
            )
            return device_id, enriched, True
        if diff_ok and _diff_has_changes(pre_diff_text):
            pre_diff_artifact_ref = await artifact_service.store(
                content=pre_diff_text,
                kind=_DIFF_ARTIFACT_KIND_PRE,
                device_id=device_id,
                run_id=context_run_id,
                media_type="text/plain",
            )
        elif not diff_ok:
            logger.warning(
                "%s pre-replace diff check failed device=%s host=%s error=%s -- proceeding "
                "with replace unverified",
                _STEP_ID,
                device_id,
                bag.get("host"),
                diff_err,
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
    ok, command_entries, err = await _run_shim_job(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        commands=[replace_command, _CONFIRM_COMMAND],
    )
    if not ok:
        return _fail_replace(device=device, device_id=device_id, node_id=node_id, error=err)

    replace_error = (command_entries.get(replace_command) or {}).get("error")
    if replace_error:
        return _fail_replace(
            device=device, device_id=device_id, node_id=node_id, error=replace_error
        )
    logger.info(
        "%s replace returned device=%s host=%s elapsed=%.1fs",
        _STEP_ID,
        device_id,
        bag.get("host"),
        time.monotonic() - started,
    )

    confirm_entry = command_entries.get(_CONFIRM_COMMAND) or {}
    if confirm_entry.get("error"):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="confirm_failed",
            message=(
                f"'configure replace' succeeded but sending '{_CONFIRM_COMMAND}' on the same "
                f"connection failed ({confirm_entry['error']}); device will auto-revert after "
                f"{timeout_minutes} minute(s)"
            ),
        )
    confirm_raw = confirm_entry.get("raw")

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

    post_diff_artifact_ref = None
    if verify_diff_after_replace:
        diff_ok, post_diff_text, diff_err = await _run_diff(
            shim, shim_credentials, shim_device=shim_device, diff_command=diff_command
        )
        if not diff_ok:
            return _fail_device(
                device=_device_with_diff_refs(
                    device,
                    node_id,
                    pre_diff_artifact_ref=pre_diff_artifact_ref,
                    post_diff_artifact_ref=None,
                ),
                device_id=device_id,
                node_id=node_id,
                code="post_verify_failed",
                message=(
                    f"'configure confirm' succeeded but the post-replace diff check failed "
                    f"({diff_err}); the running configuration could not be verified against "
                    f"{file_system}{destination_filename}"
                ),
            )
        if _diff_has_changes(post_diff_text):
            post_diff_artifact_ref = await artifact_service.store(
                content=post_diff_text,
                kind=_DIFF_ARTIFACT_KIND_POST,
                device_id=device_id,
                run_id=context_run_id,
                media_type="text/plain",
            )
            return _fail_device(
                device=_device_with_diff_refs(
                    device,
                    node_id,
                    pre_diff_artifact_ref=pre_diff_artifact_ref,
                    post_diff_artifact_ref=post_diff_artifact_ref,
                ),
                device_id=device_id,
                node_id=node_id,
                code="diff_mismatch",
                message=(
                    f"Running configuration still differs from "
                    f"{file_system}{destination_filename} after 'configure replace'/"
                    f"'configure confirm' succeeded; see the stored diff artifact "
                    f"(artifact_id={post_diff_artifact_ref.artifact_id}) for details"
                ),
            )

    enriched = _device_with_diff_refs(
        device,
        node_id,
        pre_diff_artifact_ref=pre_diff_artifact_ref,
        post_diff_artifact_ref=None,
    )
    entry = {
        "kind": "configure_replace",
        "confirmed": True,
        "destination_filename": destination_filename,
        "file_system": file_system,
        "timeout_minutes": timeout_minutes,
    }
    parsed = dict(enriched.parsed)
    parsed[f"{node_id}.configure_replace"] = entry
    enriched = enriched.model_copy(
        update={
            "parsed": parsed,
            "capabilities": enriched.capabilities | {Capability.PARSED},
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
    skip_if_no_pending_changes = bool(merged_config.get("skip_if_no_pending_changes", True))
    verify_diff_after_replace = bool(merged_config.get("verify_diff_after_replace", True))

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
                skip_if_no_pending_changes=skip_if_no_pending_changes,
                verify_diff_after_replace=verify_diff_after_replace,
                source_credentials=source_credentials,
                source_errors=source_errors,
                artifact_service=artifact_service,
                context_run_id=context.run_id,
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
