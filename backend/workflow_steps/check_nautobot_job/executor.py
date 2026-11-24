"""Executor for the check-nautobot-job workflow step.

Polls a Nautobot job result's status once per device — check, sleep, check again — up to a
configured maximum number of checks, and routes to ``success`` only when the job's own result
status is ``SUCCESS``. Everything else (the job's own result is ``FAILURE``/``REVOKED``, it
never reached a terminal state within the check budget, or a check's REST call itself errored)
routes to ``failure`` — there are only two outcomes, so every non-success case collapses into
one.

This is a plain bounded Python loop, not a Hatchet durable wait: a step executor has no access
to Hatchet's ``DurableContext`` (only the parent orchestration does), and the configured total
wait is capped well under any Hatchet task's execution timeout — see doc/WORKFLOW-STEPS.md.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotError,
    NautobotValidationError,
)
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.jobs import NautobotJobsService
from workflow_steps.check_nautobot_job.config import get_config
from workflow_steps.common.attribute_expression import resolve_attribute_expression
from workflow_steps.common.device_location_sync import uuid_or_none
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_int_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "check-nautobot-job"
_NO_JOB_UUID = FailureInfo(phase="config", kind="bad_request")

_READY_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})
_SUCCESS_STATE = "SUCCESS"
_MAX_TOTAL_WAIT_SECONDS = 600


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    job_uuid_expr: str
    max_checks: int
    interval_seconds: int
    bag_name: str


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = str(config.get("nautobot_source_id") or defaults["nautobot_source_id"]).strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is required")

    job_uuid_expr = str(config.get("job_uuid") or defaults["job_uuid"]).strip()
    if not job_uuid_expr:
        raise ValueError(f"{_STEP_ID}: job_uuid is required")

    max_checks = parse_int_flag(
        config, "max_checks", default=defaults["max_checks"], minimum=1, step_id=_STEP_ID
    )
    interval_seconds = parse_int_flag(
        config, "interval_seconds", default=defaults["interval_seconds"], step_id=_STEP_ID
    )

    total_wait = max_checks * interval_seconds
    if total_wait > _MAX_TOTAL_WAIT_SECONDS:
        raise ValueError(
            f"{_STEP_ID}: max_checks * interval_seconds = {total_wait}s exceeds the "
            f"{_MAX_TOTAL_WAIT_SECONDS}s ceiling"
        )

    bag_name = str(config.get("bag_name") or defaults["bag_name"]).strip() or "nautobot_job"

    return _ParsedConfig(
        source_id=source_id,
        job_uuid_expr=job_uuid_expr,
        max_checks=max_checks,
        interval_seconds=interval_seconds,
        bag_name=bag_name,
    )


def _apply_check_result(
    device: DeviceContext,
    *,
    job_uuid: str,
    status: str | None,
    checks_performed: int,
    bag_name: str = "nautobot_job",
) -> DeviceContext:
    existing = device.attribute_bags.get(bag_name)
    base = dict(existing) if isinstance(existing, dict) else {}
    bag = {
        **base,
        "job_result_id": job_uuid,
        "status": status,
        "checks_performed": checks_performed,
    }
    return device.model_copy(
        update={
            "attribute_bags": {**device.attribute_bags, bag_name: bag},
            "capabilities": device.capabilities | {Capability.NAUTOBOT_JOB},
        }
    )


async def _check_job_for_device(
    *,
    device: DeviceContext,
    jobs_service: NautobotJobsService,
    parsed: _ParsedConfig,
    run_id: str | None,
) -> DeviceContext | Fail:
    job_uuid = resolve_attribute_expression(device, parsed.job_uuid_expr, run_id=run_id)
    if job_uuid is None:
        return Fail("job_uuid_missing", "job_uuid has no value for this device", _NO_JOB_UUID)

    # The id goes into a REST path: only a UUID may (W6-10). The value is never echoed.
    checked_uuid = uuid_or_none(job_uuid)
    if checked_uuid is None:
        return Fail(
            "job_uuid_invalid",
            "job_uuid is not a Nautobot job result UUID",
            FailureInfo(phase="config", kind="bad_request"),
        )
    job_uuid = checked_uuid

    status: str | None = None
    last_error: Exception | None = None
    attempts = 0

    for attempt in range(parsed.max_checks):
        attempts = attempt + 1
        try:
            result = await jobs_service.get_job_result(job_uuid)
            raw_status = result.get("status")
            if isinstance(raw_status, dict):
                raw_status = raw_status.get("value")
            status = str(raw_status or "").upper()
            last_error = None
        except (NautobotAPIError, NautobotValidationError) as exc:
            last_error = exc
            status = None

        if status in _READY_STATES:
            break

        if attempt < parsed.max_checks - 1:
            await asyncio.sleep(parsed.interval_seconds)

    updated = _apply_check_result(
        device,
        job_uuid=job_uuid,
        status=status,
        checks_performed=attempts,
        bag_name=parsed.bag_name,
    )

    if status == _SUCCESS_STATE:
        return updated.model_copy(update={"status": DeviceStatus.OK})

    failure: FailureInfo | None = None
    if status:
        if status in _READY_STATES:
            message = f"job did not succeed (status={status}) after {attempts} check(s)"
        else:
            message = (
                f"job still {status} after {attempts} check(s) — the job may complete later"
            )
        # The job ran and ended unsuccessfully, or never finished: a job problem, not an API one.
        failure = FailureInfo(
            phase="task",
            kind="task_failed" if status in _READY_STATES else "task_timeout",
            retryable=status not in _READY_STATES,  # a still-running job may complete later
            attempts=attempts,
            max_attempts=parsed.max_checks,
        )
    elif last_error is not None:
        message = f"could not determine job status after {attempts} check(s): {last_error}"
    else:
        message = f"job did not reach a terminal state after {attempts} check(s)"

    if failure is None and last_error is not None:
        failure = failure_from_exception(last_error)
    return Fail("job_check_failed", message, failure, device=updated)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: no artifacts, no SSH sessions

    parsed = _parse_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    credentials = resolve_nautobot_credentials(db, parsed.source_id, step_id=_STEP_ID)
    client = CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
    jobs_service = NautobotJobsService(client)
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s node_id=%s max_checks=%d interval_seconds=%d devices=%d",
        _STEP_ID,
        log_run_id(run),
        node_id,
        parsed.max_checks,
        parsed.interval_seconds,
        len(context.devices),
    )

    async def work(_device_key: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _check_job_for_device(
            device=device, jobs_service=jobs_service, parsed=parsed, run_id=run_id
        )

    batch = await run_per_device(
        context, work, node_id=node_id, step_id=_STEP_ID, keep_text=(NautobotError,)
    )
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(batch.ok),
        len(batch.failed),
        log_run_id(run),
    )
    return build_outcomes(context, batch.ok, batch.failed)
