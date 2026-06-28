"""Hatchet child workflow that processes a subset of devices through downstream steps.

Spawned by the parent WorkflowExecution task when an inventory step has fan-out
enabled. Each instance receives a WorkflowContext pre-populated with its device
group and runs the downstream subgraph without writing WorkflowStepResult records
(the parent aggregates and persists the returned outcomes).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from hatchet.client import hatchet

logger = logging.getLogger(__name__)


class DeviceGroupInput(BaseModel):
    parent_run_id: int
    context_json: str   # serialized WorkflowContext with this group's devices only
    start_node_id: str  # inventory step's node_id; child runs nodes downstream of this
    child_index: int    # for logging / tracing
    join_node_id: str | None = None  # fan-in node; child stops before it (parent resumes)


child_workflow = hatchet.workflow(
    name="DeviceGroupExecution",
    input_validator=DeviceGroupInput,
)


@child_workflow.task(name="execute_device_group", execution_timeout=timedelta(hours=1))
async def execute_device_group(input: DeviceGroupInput, ctx: Context) -> dict[str, Any]:
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
    from services.execution.step_runner import StepRunner

    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.parent_run_id)
        if run_result is None:
            raise ValueError(
                f"DeviceGroupExecution: WorkflowRun {input.parent_run_id} not found"
            )
        run, _ = run_result

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(
                f"DeviceGroupExecution: Workflow {run.workflow_id} not found"
            )
        wf, _ = wf_result

        nodes: list[dict[str, Any]] = wf.canvas_nodes or []
        edges: list[dict[str, Any]] = wf.canvas_edges or []

        initial_context = WorkflowContext.model_validate_json(input.context_json)
        # Children run up to (but not including) the fan-in node; the parent runs
        # the fan-in node and everything downstream of it once after the rejoin.
        allowed_ids = StepRunner._child_node_ids(
            input.start_node_id, input.join_node_id, nodes, edges
        )

        runner = StepRunner(db)
        step_outcomes = await runner.execute_subgraph(
            run=run,
            workflow=wf,
            initial_context=initial_context,
            inventory_node_id=input.start_node_id,
            allowed_node_ids=allowed_ids,
        )

    # Serialize outcomes for parent aggregation; exclude the inventory step itself
    result: dict[str, Any] = {}
    for node_id, outcomes in step_outcomes.items():
        if node_id == input.start_node_id:
            continue
        result[node_id] = {
            outcome_name: context_val.model_dump(mode="json")
            for outcome_name, context_val in outcomes.items()
        }

    device_count = len(initial_context.devices)
    logger.info(
        "DeviceGroupExecution completed parent_run_id=%s child_index=%s devices=%d nodes=%d",
        input.parent_run_id,
        input.child_index,
        device_count,
        len(result),
    )
    return result
