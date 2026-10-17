"""Hatchet child workflow that processes a subset of devices through downstream steps.

Spawned by the parent WorkflowExecution task when an inventory step has fan-out
enabled. Each instance receives a WorkflowContext pre-populated with its device
group and runs the downstream subgraph without writing WorkflowStepResult records
(the parent aggregates and persists the returned outcomes).
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any
from uuid import uuid4

from hatchet_sdk import Context
from pydantic import BaseModel

from hatchet.client import hatchet
from services.workflow_context.secret_fields import scrub_known_secrets, with_run_secret_scope

logger = logging.getLogger(__name__)

# A child result above this size is logged as a warning (it is sent to the parent via Hatchet).
_RESULT_WARN_BYTES = 1024 * 1024


class DeviceGroupInput(BaseModel):
    parent_run_id: int
    context_json: str  # serialized WorkflowContext with this group's devices only
    start_node_id: str  # inventory step's node_id; child runs nodes downstream of this
    child_index: int  # for logging / tracing
    join_node_id: str | None = None  # fan-in node; child stops before it (parent resumes)


child_workflow = hatchet.workflow(
    name="DeviceGroupExecution",
    input_validator=DeviceGroupInput,
)


@child_workflow.task(name="execute_device_group", execution_timeout=timedelta(hours=1))
async def execute_device_group(input: DeviceGroupInput, ctx: Context) -> dict[str, Any]:
    return await run_device_group(input)


def _report_group(action: str, **kwargs: Any) -> None:
    """Best-effort update of this child's ``WorkflowRunDeviceGroup`` row.

    Uses its own short-lived session so a progress write can never disturb (or be
    disturbed by) the session the step executors run on. Never raises: progress
    reporting must not fail a device run.
    """
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    try:
        with SessionLocal() as db:
            getattr(RunRepository(db), action)(**kwargs)
    except Exception:
        logger.warning("Failed to record device-group %s %s", action, kwargs, exc_info=True)


async def run_device_group(input: DeviceGroupInput) -> dict[str, Any]:
    _report_group(
        "mark_device_group_started",
        run_id=input.parent_run_id,
        child_index=input.child_index,
    )
    try:
        return await _run_device_group(input)
    except Exception as exc:
        # The row is shown to users: a fixed message plus an id for the worker log, never
        # str(exc), which can carry device text or a secret.
        error_id = str(uuid4())
        logger.exception(
            "DeviceGroupExecution failed parent_run_id=%s child_index=%s error_id=%s",
            input.parent_run_id,
            input.child_index,
            error_id,
        )
        _report_group(
            "finish_device_group",
            run_id=input.parent_run_id,
            child_index=input.child_index,
            status="failed",
            error_message=(
                f"The device group failed ({type(exc).__name__}); see the worker log, "
                f"error id {error_id}"
            ),
        )
        raise


@with_run_secret_scope
async def _run_device_group(input: DeviceGroupInput) -> dict[str, Any]:
    # The secret registry must outlive execute_subgraph: the result below is serialized for the
    # parent (which persists it) and must be scrubbed of every secret the child decrypted (W6).
    logger.info(
        "DeviceGroupExecution starting parent_run_id=%s child_index=%s start_node_id=%s",
        input.parent_run_id,
        input.child_index,
        input.start_node_id,
    )

    from core.database import SessionLocal
    from models.workflow_context import WorkflowContext
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.graph import child_node_ids
    from services.execution.step_runner import StepRunner
    from services.execution.step_runner.progress import DeviceGroupProgressSink

    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.parent_run_id)
        if run_result is None:
            raise ValueError(f"DeviceGroupExecution: WorkflowRun {input.parent_run_id} not found")
        run, _ = run_result

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"DeviceGroupExecution: Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        initial_context = WorkflowContext.model_validate_json(input.context_json)
        runner = StepRunner(db)
        # The graph the parent aggregates against (funnels, disabled steps, stop-here resolved).
        nodes, edges = runner.load_execution_graph(wf)
        # Children run up to (but not including) the fan-in node; the parent runs
        # the fan-in node and everything downstream of it once after the rejoin.
        allowed_ids = child_node_ids(input.start_node_id, input.join_node_id, nodes, edges)

        progress = DeviceGroupProgressSink(
            run_repo, run_id=input.parent_run_id, child_index=input.child_index
        )
        try:
            step_outcomes, step_errors = await runner.execute_subgraph(
                run=run,
                workflow=wf,
                initial_context=initial_context,
                inventory_node_id=input.start_node_id,
                allowed_node_ids=allowed_ids,
                progress=progress,
                child_index=input.child_index,
            )
        finally:
            # This is where session reuse pays off most: a per-device child
            # runs its whole downstream chain over a single SSH login.
            await runner.close_device_sessions()

    _report_group(
        "finish_device_group",
        run_id=input.parent_run_id,
        child_index=input.child_index,
        status="failed" if step_errors else progress.overall_status(),
    )

    # Serialize outcomes for parent aggregation; exclude the inventory step itself.
    # "__step_errors__" is a reserved key (not a canvas node_id) carrying
    # node_id -> {message, category, error_id} for nodes whose executor raised.
    result: dict[str, Any] = {
        "__step_errors__": {
            node_id: {**err, "message": scrub_known_secrets(err.get("message", ""))}
            for node_id, err in step_errors.items()
        }
    }
    for node_id, outcomes in step_outcomes.items():
        if node_id == input.start_node_id:
            continue
        result[node_id] = {
            outcome_name: scrub_known_secrets(context_val.model_dump(mode="json"))
            for outcome_name, context_val in outcomes.items()
        }

    # The child result travels through Hatchet to the parent: measure it so an operator can see
    # when a large fan-out approaches the engine's payload limits. Nothing is capped here (DN-E).
    result_bytes = len(json.dumps(result, default=str).encode("utf-8"))
    log_result = logger.warning if result_bytes > _RESULT_WARN_BYTES else logger.info
    log_result(
        "DeviceGroupExecution result bytes=%d parent_run_id=%s child_index=%s",
        result_bytes,
        input.parent_run_id,
        input.child_index,
    )

    device_count = len(initial_context.devices)
    logger.info(
        "DeviceGroupExecution completed parent_run_id=%s child_index=%s devices=%d nodes=%d",
        input.parent_run_id,
        input.child_index,
        device_count,
        len(result),
    )
    return result
