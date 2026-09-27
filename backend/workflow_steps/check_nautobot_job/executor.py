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
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotAPIError, NautobotValidationError
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.jobs import NautobotJobsService
from workflow_steps.check_nautobot_job.config import get_config
from workflow_steps.common.attribute_expression import resolve_attribute_expression
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "check-nautobot-job"

_READY_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})
_SUCCESS_STATE = "SUCCESS"
_MAX_TOTAL_WAIT_SECONDS = 120


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    job_uuid_expr: str
    max_checks: int
    interval_seconds: int


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = str(config.get("nautobot_source_id") or defaults["nautobot_source_id"]).strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is required")

    job_uuid_expr = str(config.get("job_uuid") or defaults["job_uuid"]).strip()
    if not job_uuid_expr:
        raise ValueError(f"{_STEP_ID}: job_uuid is required")

    try:
        max_checks = int(config.get("max_checks", defaults["max_checks"]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_STEP_ID}: max_checks must be an integer") from exc
    if max_checks < 1:
        raise ValueError(f"{_STEP_ID}: max_checks must be at least 1")

    try:
        interval_seconds = int(config.get("interval_seconds", defaults["interval_seconds"]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_STEP_ID}: interval_seconds must be an integer") from exc
    if interval_seconds < 0:
        raise ValueError(f"{_STEP_ID}: interval_seconds must be at least 0")

    total_wait = max_checks * interval_seconds
    if total_wait > _MAX_TOTAL_WAIT_SECONDS:
        raise ValueError(
            f"{_STEP_ID}: max_checks * interval_seconds = {total_wait}s exceeds the "
            f"{_MAX_TOTAL_WAIT_SECONDS}s ceiling"
        )

    return _ParsedConfig(
        source_id=source_id,
        job_uuid_expr=job_uuid_expr,
        max_checks=max_checks,
        interval_seconds=interval_seconds,
    )


def _fail_device(
    *, device_key: str, device: DeviceContext, node_id: str, exc: Exception
) -> tuple[str, DeviceContext]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=type(exc).__name__.lower(),
        message=str(exc),
    )
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_key, failed


def _apply_check_result(
    device: DeviceContext,
    *,
    job_uuid: str,
    status: str | None,
    checks_performed: int,
) -> DeviceContext:
    existing = device.attribute_bags.get("nautobot_job")
    base = dict(existing) if isinstance(existing, dict) else {}
    bag = {
        **base,
        "job_result_id": job_uuid,
        "status": status,
        "checks_performed": checks_performed,
    }
    return device.model_copy(
        update={
            "attribute_bags": {**device.attribute_bags, "nautobot_job": bag},
            "capabilities": device.capabilities | {Capability.NAUTOBOT_JOB},
        }
    )


async def _check_job_for_device(
    *,
    device_key: str,
    device: DeviceContext,
    node_id: str,
    jobs_service: NautobotJobsService,
    parsed: _ParsedConfig,
    run_id: str | None,
) -> tuple[str, DeviceContext, bool]:
    job_uuid = resolve_attribute_expression(device, parsed.job_uuid_expr, run_id=run_id)
    if job_uuid is None:
        key, failed = _fail_device(
            device_key=device_key,
            device=device,
            node_id=node_id,
            exc=ValueError("job_uuid has no value for this device"),
        )
        return key, failed, False

    status: str | None = None
    last_error: Exception | None = None
    attempts = 0

    for attempt in range(parsed.max_checks):
        attempts = attempt + 1
        try:
            result = await jobs_service.get_job_result(job_uuid)
            status = str(result.get("status") or "").upper()
            last_error = None
        except (NautobotAPIError, NautobotValidationError) as exc:
            last_error = exc
            status = None

        if status in _READY_STATES:
            break

        if attempt < parsed.max_checks - 1:
            await asyncio.sleep(parsed.interval_seconds)

    updated = _apply_check_result(
        device, job_uuid=job_uuid, status=status, checks_performed=attempts
    )

    if status == _SUCCESS_STATE:
        return device_key, updated.model_copy(update={"status": DeviceStatus.OK}), True

    if status:
        message = f"job did not succeed (status={status}) after {attempts} check(s)"
    elif last_error is not None:
        message = f"could not determine job status after {attempts} check(s): {last_error}"
    else:
        message = f"job did not reach a terminal state after {attempts} check(s)"

    key, failed = _fail_device(
        device_key=device_key, device=updated, node_id=node_id, exc=RuntimeError(message)
    )
    return key, failed, False


def _build_outcomes(
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes


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
        run.id,
        node_id,
        parsed.max_checks,
        parsed.interval_seconds,
        len(context.devices),
    )

    results = await asyncio.gather(
        *[
            _check_job_for_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                jobs_service=jobs_service,
                parsed=parsed,
                run_id=run_id,
            )
            for device_key, device in context.devices.items()
        ]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, device, ok in results:
        if ok:
            success_devices[device_key] = device
        else:
            failed_devices[device_key] = device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_outcomes(context, success_devices, failed_devices)
