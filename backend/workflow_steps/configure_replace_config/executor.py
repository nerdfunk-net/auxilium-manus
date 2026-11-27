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

import logging
import time
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.pyats.batch import cap_shim_text, shim_concurrency
from services.pyats.credentials import PyATSCredentials
from services.workflow_context.node_result import set_node_result
from services.workflow_context.secret_fields import unwrap_secret
from workflow_steps.common.device_file_upload import parse_device_token
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.failure_records import COMMAND_FAILED, INVALID_INPUT
from workflow_steps.common.pyats_batch import resolve_source_credentials
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.configure_replace_config.config import get_config
from workflow_steps.configure_replace_config.diff_checks import (
    Target,
    build_diff_command,
    device_with_diff_refs,
    pre_replace_diff,
    verify_after_replace,
)
from workflow_steps.configure_replace_config.shim_jobs import (
    STEP_ID,
    run_shim_job,
)

if TYPE_CHECKING:

    from services.network.netmiko.session_pool import DeviceSessionPool


logger = logging.getLogger(__name__)


_CONFIRM_COMMAND = "configure confirm"
_MIN_TIMEOUT_MINUTES = 1
_MIN_JOB_TIMEOUT_SECONDS = 30
_MAX_JOB_TIMEOUT_SECONDS = 600
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


_OUTCOME_UNKNOWN_WARNING = (
    " -- the job may still have been applied on the device; check it before re-running"
)


def _replace_failure(
    error: str | None, *, failure: FailureInfo | None = None, outcome_unknown: bool = False
) -> Fail:
    """Fail a device for a 'configure replace' error, whether it surfaced as a
    connection/job-level failure or as a per-command error on an otherwise-connected
    session -- both land here so the archive-not-configured hint stays in one place.

    ``outcome_unknown`` (the client gave up waiting) is a ``task_timeout`` with a warning:
    distinguishable from a refusal, which keeps its own ``failure``."""
    if _is_archive_not_configured_error(error):
        return Fail(
            "archive_not_configured",
            "Device rejected 'configure replace' because config archiving is not "
            "enabled -- the 'time'/Rollback Confirmed Change feature this step relies "
            "on requires it. Configure it once on the device, e.g.:\n"
            "  archive\n"
            "   path flash:archive\n"
            "then retry. See this step's Help panel for details.",
            failure=INVALID_INPUT,
        )
    # The archive hint reads the whole text; what is stored is capped (R4-01).
    error = cap_shim_text(error) if error else error
    if outcome_unknown:
        return Fail(
            "replace_failed",
            f"'configure replace' failed or the connection was lost: {error}"
            f"{_OUTCOME_UNKNOWN_WARNING}",
            FailureInfo(phase="task", kind="task_timeout", hint="retry_later"),
        )
    return Fail(
        "replace_failed", f"'configure replace' failed or the connection was lost: {error}", failure
    )


def _prepare_target(
    *,
    device_id: str,
    device: DeviceContext,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
    job_timeout: float,
) -> Target | Fail:
    """Resolve the testbed bag, pyATS source and password; a ``Fail`` on error."""
    bag = device.attribute_bags.get("pyats_testbed")
    if not isinstance(bag, dict):
        return Fail(
            "missing_testbed", "No pyats_testbed bag found -- add an Add Testbed step upstream",
            failure=INVALID_INPUT,
        )

    source_id = str(bag.get("pyats_source_id") or "")
    if source_id in source_errors:
        return Fail("source_error", source_errors[source_id], failure=INVALID_INPUT)
    shim_credentials = source_credentials.get(source_id)
    if shim_credentials is None:
        return Fail(
            "source_error",
            f"pyATS source {source_id!r} could not be resolved",
            failure=INVALID_INPUT,
        )

    password = unwrap_secret(bag.get("password"))
    if not password:
        return Fail(
            "missing_credential",
            "pyats_testbed bag has no usable password",
            failure=INVALID_INPUT,
        )

    shim_device = {
        "name": device_id,
        "host": bag.get("host"),
        "os": bag.get("os"),
        "username": bag.get("username"),
        "password": password,
    }
    return Target(
        bag=bag,
        source_id=source_id,
        shim=service_factory.get_pyats_app_service(),
        shim_credentials=shim_credentials,
        shim_device=shim_device,
        job_timeout=job_timeout,
    )


async def _replace_and_confirm(
    target: Target,
    *,
    device_id: str,
    destination_filename: str,
    file_system: str,
    timeout_minutes: int,
) -> Fail | None:
    """Send ``configure replace`` + ``configure confirm`` on one connection.
    Returns a ``Fail``, or None when the replace was confirmed."""
    replace_command = (
        f"configure replace {file_system}{destination_filename} force time {timeout_minutes}"
    )
    logger.info(
        "%s replace device=%s host=%s command=%s",
        STEP_ID,
        device_id,
        target.bag.get("host"),
        replace_command,
    )
    started = time.monotonic()
    job = await run_shim_job(
        target.shim,
        target.shim_credentials,
        operation="execute",
        shim_device=target.shim_device,
        commands=[replace_command, _CONFIRM_COMMAND],
        timeout=target.job_timeout,
    )
    if not job.ok:
        return _replace_failure(job.error, failure=job.failure, outcome_unknown=job.outcome_unknown)
    command_entries = job.entries

    replace_error = (command_entries.get(replace_command) or {}).get("error")
    if replace_error:
        return _replace_failure(replace_error)
    logger.info(
        "%s replace returned device=%s host=%s elapsed=%.1fs",
        STEP_ID,
        device_id,
        target.bag.get("host"),
        time.monotonic() - started,
    )

    confirm_entry = command_entries.get(_CONFIRM_COMMAND) or {}
    if confirm_entry.get("error"):
        return Fail(
            "confirm_failed",
            f"'configure replace' succeeded but sending '{_CONFIRM_COMMAND}' on the same "
            f"connection failed ({cap_shim_text(str(confirm_entry['error']))}); device will "
            f"auto-revert after "
            f"{timeout_minutes} minute(s)",
            failure=COMMAND_FAILED,
        )

    if _has_no_pending_rollback(confirm_entry.get("raw")):
        return Fail(
            "confirm_not_pending",
            f"Device reported no pending Rollback Confirmed Change when "
            f"'{_CONFIRM_COMMAND}' was sent -- the timed replace may have already reverted "
            f"or been confirmed by another session; verify the running configuration "
            f"manually",
        )
    return None


def _confirmed_result(
    device: DeviceContext,
    *,
    node_id: str,
    pre_diff_artifact_ref: Any | None,
    destination_filename: str,
    file_system: str,
    timeout_minutes: int,
) -> DeviceContext:
    enriched = device_with_diff_refs(
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
    parsed = set_node_result(enriched.parsed, node_id, "configure_replace", entry)
    enriched = enriched.model_copy(
        update={
            "parsed": parsed,
            "capabilities": enriched.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    return enriched


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
    job_timeout: float,
    artifact_service: ArtifactService,
    context_run_id: str,
) -> DeviceContext | Fail:
    target = _prepare_target(
        device_id=device_id,
        device=device,
        source_credentials=source_credentials,
        source_errors=source_errors,
        job_timeout=job_timeout,
    )
    if isinstance(target, Fail):
        return target

    logger.info(
        "%s replace starting device=%s host=%s os=%s source=%s",
        STEP_ID,
        device_id,
        target.bag.get("host"),
        target.bag.get("os"),
        target.source_id,
    )

    diff_command = build_diff_command(
        file_system=file_system, destination_filename=destination_filename
    )
    pre_diff_artifact_ref = None
    if skip_if_no_pending_changes:
        pre = await pre_replace_diff(
            target,
            device_id=device_id,
            device=device,
            node_id=node_id,
            diff_command=diff_command,
            destination_filename=destination_filename,
            file_system=file_system,
            timeout_minutes=timeout_minutes,
            artifact_service=artifact_service,
            context_run_id=context_run_id,
        )
        if pre.skipped is not None:
            return pre.skipped
        pre_diff_artifact_ref = pre.artifact_ref

    failed = await _replace_and_confirm(
        target,
        device_id=device_id,
        destination_filename=destination_filename,
        file_system=file_system,
        timeout_minutes=timeout_minutes,
    )
    if failed is not None:
        return failed

    if verify_diff_after_replace:
        failed = await verify_after_replace(
            target,
            device_id=device_id,
            device=device,
            node_id=node_id,
            diff_command=diff_command,
            destination_filename=destination_filename,
            file_system=file_system,
            pre_diff_artifact_ref=pre_diff_artifact_ref,
            artifact_service=artifact_service,
            context_run_id=context_run_id,
        )
        if failed is not None:
            return failed

    return _confirmed_result(
        device,
        node_id=node_id,
        pre_diff_artifact_ref=pre_diff_artifact_ref,
        destination_filename=destination_filename,
        file_system=file_system,
        timeout_minutes=timeout_minutes,
    )


def _parse_job_timeout(value: Any) -> float:
    """Per-job budget in seconds, same bound as the shim's ``JobRequest.timeout_seconds``."""
    if value is None or value == "":
        return float(get_config()["job_timeout_seconds"])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{STEP_ID}: job_timeout_seconds must be a number")
    if not (_MIN_JOB_TIMEOUT_SECONDS <= value <= _MAX_JOB_TIMEOUT_SECONDS):
        raise ValueError(
            f"{STEP_ID}: job_timeout_seconds must be between {_MIN_JOB_TIMEOUT_SECONDS} and "
            f"{_MAX_JOB_TIMEOUT_SECONDS}"
        )
    return float(value)


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
        raise ValueError(f"{STEP_ID}: destination_filename is required")
    parse_device_token(destination_filename, name="destination_filename", step_id=STEP_ID)
    file_system = str(merged_config.get("file_system") or "").strip()
    if not file_system:
        raise ValueError(f"{STEP_ID}: file_system is required")
    parse_device_token(file_system, name="file_system", step_id=STEP_ID)
    timeout_minutes = parse_int_flag(
        config,
        "timeout_minutes",
        default=get_config()["timeout_minutes"],
        minimum=_MIN_TIMEOUT_MINUTES,
        maximum=_MAX_TIMEOUT_MINUTES,
        step_id=STEP_ID,
    )
    job_timeout_seconds = _parse_job_timeout(merged_config.get("job_timeout_seconds"))
    skip_if_no_pending_changes = parse_bool_flag(
        merged_config, "skip_if_no_pending_changes", default=True
    )
    verify_diff_after_replace = parse_bool_flag(
        merged_config, "verify_diff_after_replace", default=True
    )

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d destination_filename=%s file_system=%s "
        "timeout_minutes=%d",
        STEP_ID,
        log_run_id(run),
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
    source_credentials, source_errors = resolve_source_credentials(db, source_ids)

    # At most as many jobs in flight as the shim runs at once, so it never has to queue them:
    # a job that waited in the shim's queue could outlive the client's timeout and still run.
    # The shim's own limit (from /health/pyats), or the default of 4 when it cannot be read.
    parallel_jobs = (
        await shim_concurrency(
            service_factory.get_pyats_app_service(), next(iter(source_credentials.values()))
        )
        if source_credentials
        else 4
    )

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _process_one_device(
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
            job_timeout=job_timeout_seconds,
            artifact_service=artifact_service,
            context_run_id=context.run_id,
        )

    # Any problem of one device (a shim request it refuses, an artifact that cannot be stored)
    # fails that device only; the runner keeps the others going.
    batch = await run_per_device(
        context, work, node_id=node_id, step_id=STEP_ID, concurrency=parallel_jobs
    )
    success_devices, failed_devices = batch.ok, batch.failed

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        STEP_ID,
        len(success_devices),
        len(failed_devices),
        log_run_id(run),
    )
    return build_outcomes(context, success_devices, failed_devices)

