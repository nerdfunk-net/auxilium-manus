from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from hatchet_sdk import Context
from pydantic import BaseModel

from hatchet.client import hatchet
from hatchet.workflows.device_group_execution import DeviceGroupInput, child_workflow

if TYPE_CHECKING:
    from models.workflow_context import WorkflowContext

logger = logging.getLogger(__name__)


class WorkflowRunInput(BaseModel):
    run_id: int


workflow = hatchet.workflow(
    name="WorkflowExecution",
    on_events=["workflow:run"],
    input_validator=WorkflowRunInput,
)


@workflow.task(name="prepare", execution_timeout=timedelta(seconds=30))
async def prepare(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Preparing workflow run run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        repo = RunRepository(db)
        result = repo.get_run_by_id(input.run_id)
        if result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = result
        repo.update_run_status(
            run,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

    return {"run_id": input.run_id}


@workflow.task(name="execute_steps", parents=[prepare], execution_timeout=timedelta(hours=1))
async def execute_steps(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import FanOutSignal, StepRunner

    # Phase 1: run in topological order until completion or a fan-out signal
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = run_result

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        runner = StepRunner(db)
        result = await runner.execute_all(run=run, workflow=wf)

        if not isinstance(result, FanOutSignal):
            final_status = "success" if result else "failed"
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(timezone.utc),
            )
            logger.info("Run finished run_id=%s status=%s", input.run_id, final_status)
            return {"run_id": input.run_id, "status": final_status}

        signal = result
        # Capture workflow graph before session closes
        canvas_nodes: list[dict[str, Any]] = wf.canvas_nodes or []
        canvas_edges: list[dict[str, Any]] = wf.canvas_edges or []

    # Phase 2: dispatch child workflows (DB session intentionally closed)
    logger.info(
        "Fan-out started run_id=%s mode=%s max_concurrency=%s",
        input.run_id,
        signal.fan_out_config.get("mode"),
        signal.fan_out_config.get("max_concurrency"),
    )
    child_results = await _dispatch_children(signal, input.run_id)

    # Phase 3: aggregate child outcomes and persist to parent run step results
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found (phase 3)")
        run, _ = run_result

        success, child_merged = _aggregate_and_persist(
            run_repo=run_repo,
            run_id=run.id,
            signal=signal,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            child_results=child_results,
        )

        # Phase 4: when a fan-in node exists, resume execution once on the merged
        # (fanned-in) context so git/store steps after the join run exactly once.
        if signal.join_node_id is not None:
            wf_result = wf_repo.get_by_id(run.workflow_id)
            if wf_result is None:
                raise ValueError(
                    f"Workflow {run.workflow_id} not found (phase 4 resume)"
                )
            wf, _ = wf_result

            # The fan-in node's parents are child-branch nodes; the inventory
            # node is included so a join wired directly to it still resolves.
            merged_outcomes: dict[str, dict[str, Any]] = {
                signal.inventory_node_id: {"success": signal.inventory_outcome}
            }
            merged_outcomes.update(child_merged)

            logger.info(
                "Fan-in resume run_id=%s join_node_id=%s",
                input.run_id,
                signal.join_node_id,
            )
            join_success = await StepRunner(db).resume_after_join(
                run=run,
                workflow=wf,
                merged_outcomes=merged_outcomes,
                join_node_id=signal.join_node_id,
            )
            success = success and join_success

        final_status = "success" if success else "failed"
        run_repo.update_run_status(
            run,
            status=final_status,
            finished_at=datetime.now(timezone.utc),
        )

    logger.info("Run finished (fan-out) run_id=%s status=%s", input.run_id, final_status)
    return {"run_id": input.run_id, "status": final_status}


async def _dispatch_children(
    signal: Any,
    parent_run_id: int,
) -> list[dict[str, Any] | BaseException]:
    """Split devices into groups and dispatch Hatchet child workflows."""
    from services.execution.step_runner import FanOutSignal

    assert isinstance(signal, FanOutSignal)

    fan_out_config = signal.fan_out_config
    mode = fan_out_config.get("mode", "per_device")
    chunk_size = max(1, int(fan_out_config.get("chunk_size", 1)))
    max_concurrency = max(0, int(fan_out_config.get("max_concurrency", 0)))

    all_devices = signal.inventory_outcome.devices
    device_ids = list(all_devices.keys())

    if mode == "chunked":
        groups = [
            device_ids[i : i + chunk_size]
            for i in range(0, len(device_ids), chunk_size)
        ]
    else:
        groups = [[did] for did in device_ids]

    if not groups:
        return []

    child_inputs: list[DeviceGroupInput] = []
    for i, group_ids in enumerate(groups):
        group_devices = {did: all_devices[did] for did in group_ids}
        group_context = signal.inventory_outcome.model_copy(
            update={"devices": group_devices}
        )
        child_inputs.append(
            DeviceGroupInput(
                parent_run_id=parent_run_id,
                context_json=group_context.model_dump_json(),
                start_node_id=signal.inventory_node_id,
                child_index=i,
                join_node_id=signal.join_node_id,
            )
        )

    logger.info(
        "Dispatching %d child workflows parent_run_id=%s max_concurrency=%s",
        len(child_inputs),
        parent_run_id,
        max_concurrency,
    )

    if max_concurrency <= 0:
        tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    # Batched execution: max_concurrency child workflows at a time
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(inp: DeviceGroupInput) -> dict[str, Any]:
        async with semaphore:
            return await child_workflow.aio_run(inp)

    tasks = [_run_one(inp) for inp in child_inputs]
    return list(await asyncio.gather(*tasks, return_exceptions=True))


def _aggregate_and_persist(
    *,
    run_repo: Any,
    run_id: int,
    signal: Any,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    child_results: list[dict[str, Any] | BaseException],
) -> tuple[bool, dict[str, dict[str, WorkflowContext]]]:
    """Merge child outcomes and update the parent run's WorkflowStepResult records.

    Returns ``(no_child_failure, merged_outcomes)`` where ``merged_outcomes`` maps
    each child-branch node_id → outcome_name → merged WorkflowContext (device union
    across children). The orchestrator feeds that map into ``resume_after_join`` so
    the fan-in node's inputs resolve from the fanned-in device union.
    """
    from models.workflow_context import WorkflowContext
    from services.execution.step_runner import StepRunner
    from services.workflow_context.merge import merge_fan_out_contexts

    # Children only produce the child branch (nodes before the fan-in node). The
    # post-join nodes are run once by the parent in resume_after_join, so they must
    # NOT be marked skipped here.
    child_ids = StepRunner._child_node_ids(
        signal.inventory_node_id, signal.join_node_id, canvas_nodes, canvas_edges
    )

    # Build a lookup from node_id → step result
    all_step_results = run_repo.get_step_results_for_run(run_id)
    step_result_by_node: dict[str, Any] = {sr.step_node_id: sr for sr in all_step_results}

    # Accumulate outcomes per child-branch node across all children
    per_node: dict[str, dict[str, list[WorkflowContext]]] = {
        nid: {} for nid in child_ids
    }
    has_any_failure = False

    for child_result in child_results:
        if isinstance(child_result, BaseException):
            logger.error("Child workflow failed: %s", child_result)
            has_any_failure = True
            continue

        # child_result shape: {"execute_device_group": {node_id: {outcome_name: ctx_dict}}}
        task_output = child_result.get("execute_device_group", child_result)

        for node_id, outcomes in task_output.items():
            if node_id not in per_node:
                continue
            for outcome_name, ctx_dict in outcomes.items():
                ctx = WorkflowContext.model_validate(ctx_dict)
                per_node[node_id].setdefault(outcome_name, []).append(ctx)

    now = datetime.now(timezone.utc)
    merged_outcomes: dict[str, dict[str, WorkflowContext]] = {}

    for node_id in child_ids:
        node_outcomes = per_node[node_id]
        step_result = step_result_by_node.get(node_id)

        if not node_outcomes:
            if step_result is not None:
                run_repo.update_step_result(
                    step_result,
                    status="skipped",
                    finished_at=now,
                )
            continue

        merged_output: dict[str, Any] = {}
        node_merged: dict[str, WorkflowContext] = {}
        for outcome_name, ctx_list in node_outcomes.items():
            merged_ctx = (
                merge_fan_out_contexts(ctx_list) if len(ctx_list) > 1 else ctx_list[0]
            )
            node_merged[outcome_name] = merged_ctx
            merged_output[outcome_name] = merged_ctx.model_dump(mode="json")
        merged_outcomes[node_id] = node_merged

        if step_result is not None:
            if has_any_failure or "failure" in node_outcomes:
                status = "partial" if "success" in node_outcomes else "failed"
            else:
                status = "success"
            run_repo.update_step_result(
                step_result,
                status=status,
                output={"outcomes": merged_output},
                started_at=now,
                finished_at=now,
            )

    return not has_any_failure, merged_outcomes
