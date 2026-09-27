"""Executor for the start-nautobot-job workflow step.

Starts a Nautobot job once per device in the incoming context (see
doc/WORKFLOW-STEPS.md's per-device REST-write shape, mirrored from
update-nautobot-device), resolving each parameter value ({path} attribute expression or
literal) per device, and records the returned job result id on that device's
``attribute_bags["nautobot_job"]`` for a downstream status-check step to read.

Outcomes are about the REST call to *start* the job, not the job's own eventual result —
Nautobot hasn't run the job yet at this point, so "the job failed" isn't knowable here.
"""

from __future__ import annotations

import asyncio
import json
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
from workflow_steps.common.attribute_expression import resolve_attribute_expression
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.update_field_expression import normalize_field_spec
from workflow_steps.start_nautobot_job.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "start-nautobot-job"

_INTEGER_TYPES = frozenset({"IntegerVar"})
_BOOLEAN_TYPES = frozenset({"BooleanVar"})
_JSON_LIKE_TYPES = frozenset({"JSONVar", "MultiObjectVar", "MultiChoiceVar"})


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    job_id: str
    job_name: str
    job_variables_schema: list[dict[str, Any]]
    required_params: dict[str, str]
    optional_params: dict[str, tuple[bool, str]]
    task_queue: str | None


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = str(config.get("nautobot_source_id") or defaults["nautobot_source_id"]).strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is required")

    job_id = str(config.get("job_id") or defaults["job_id"]).strip()
    if not job_id:
        raise ValueError(f"{_STEP_ID}: job_id is required")

    job_name = str(config.get("job_name") or "").strip()

    raw_schema = config.get("job_variables_schema")
    job_variables_schema: list[dict[str, Any]] = raw_schema if isinstance(raw_schema, list) else []

    raw_parameters = config.get("parameters")
    raw_parameters = raw_parameters if isinstance(raw_parameters, dict) else {}

    raw_required = raw_parameters.get("required")
    required_params: dict[str, str] = {}
    if isinstance(raw_required, dict):
        for name, raw_value in raw_required.items():
            value = str(raw_value or "").strip()
            if value:
                required_params[str(name)] = value

    raw_optional = raw_parameters.get("optional")
    optional_params: dict[str, tuple[bool, str]] = {}
    if isinstance(raw_optional, dict):
        for name, raw_spec in raw_optional.items():
            enabled, value = normalize_field_spec(raw_spec)
            optional_params[str(name)] = (enabled, value)

    required_names = {
        str(variable.get("name"))
        for variable in job_variables_schema
        if variable.get("required") and variable.get("name")
    }
    missing = required_names - required_params.keys()
    if missing:
        raise ValueError(
            f"{_STEP_ID}: required job parameter(s) not configured: {', '.join(sorted(missing))}"
        )

    task_queue = str(config.get("task_queue") or "").strip() or None

    return _ParsedConfig(
        source_id=source_id,
        job_id=job_id,
        job_name=job_name,
        job_variables_schema=job_variables_schema,
        required_params=required_params,
        optional_params=optional_params,
        task_queue=task_queue,
    )


def _coerce_value(name: str, resolved: str, var_type: str) -> Any:
    if var_type in _INTEGER_TYPES:
        try:
            return int(resolved)
        except ValueError as exc:
            raise ValueError(f"parameter '{name}' must be an integer, got {resolved!r}") from exc

    if var_type in _BOOLEAN_TYPES:
        normalized = resolved.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no", ""):
            return False
        raise ValueError(f"parameter '{name}' must be a boolean, got {resolved!r}")

    if var_type in _JSON_LIKE_TYPES:
        stripped = resolved.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"parameter '{name}' must be valid JSON, got {resolved!r}"
                ) from exc
        if var_type == "MultiObjectVar" and "," in stripped:
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return resolved

    return resolved


def _resolve_device_params(
    *,
    device: DeviceContext,
    required_params: dict[str, str],
    optional_params: dict[str, tuple[bool, str]],
    variable_types: dict[str, str],
    run_id: str | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}

    for name, raw_expr in required_params.items():
        resolved = resolve_attribute_expression(device, raw_expr, run_id=run_id)
        if resolved is None:
            raise ValueError(f"required parameter '{name}' has no value for this device")
        data[name] = _coerce_value(name, resolved, variable_types.get(name, ""))

    for name, (enabled, raw_expr) in optional_params.items():
        if not enabled:
            continue
        resolved = resolve_attribute_expression(device, raw_expr, run_id=run_id)
        if resolved is None:
            continue
        data[name] = _coerce_value(name, resolved, variable_types.get(name, ""))

    return data


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


def _apply_job_result(
    device: DeviceContext,
    *,
    job_result_id: str,
    job_id: str,
    source_id: str,
    job_name: str,
) -> DeviceContext:
    bag = {
        "job_result_id": job_result_id,
        "job_id": job_id,
        "nautobot_source_id": source_id,
        "job_name": job_name,
    }
    return device.model_copy(
        update={
            "attribute_bags": {**device.attribute_bags, "nautobot_job": bag},
            "capabilities": device.capabilities | {Capability.NAUTOBOT_JOB},
            "status": DeviceStatus.OK,
        }
    )


async def _start_job_for_device(
    *,
    device_key: str,
    device: DeviceContext,
    node_id: str,
    jobs_service: NautobotJobsService,
    parsed: _ParsedConfig,
    variable_types: dict[str, str],
    run_id: str | None,
) -> tuple[str, DeviceContext, bool]:
    try:
        data = _resolve_device_params(
            device=device,
            required_params=parsed.required_params,
            optional_params=parsed.optional_params,
            variable_types=variable_types,
            run_id=run_id,
        )
        result = await jobs_service.run_job(
            parsed.job_id, data=data, task_queue=parsed.task_queue
        )
        job_result = result.get("job_result") if isinstance(result, dict) else None
        job_result_id = job_result.get("id") if isinstance(job_result, dict) else None
        if not job_result_id:
            raise RuntimeError("Nautobot did not return a job_result id")

        updated = _apply_job_result(
            device,
            job_result_id=str(job_result_id),
            job_id=parsed.job_id,
            source_id=parsed.source_id,
            job_name=parsed.job_name,
        )
        return device_key, updated, True
    except (NautobotAPIError, NautobotValidationError, ValueError, RuntimeError) as exc:
        key, failed = _fail_device(device_key=device_key, device=device, node_id=node_id, exc=exc)
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
    variable_types = {
        str(variable.get("name")): str(variable.get("type") or "")
        for variable in parsed.job_variables_schema
        if variable.get("name")
    }
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s node_id=%s job_id=%s devices=%d",
        _STEP_ID,
        run.id,
        node_id,
        parsed.job_id,
        len(context.devices),
    )

    results = await asyncio.gather(
        *[
            _start_job_for_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                jobs_service=jobs_service,
                parsed=parsed,
                variable_types=variable_types,
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
