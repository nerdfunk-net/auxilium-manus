from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from hatchet_sdk import Context, DurableContext
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


async def _run_steps_until_fan_out_or_done(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    wf: Any,
    ctx: DurableContext,
) -> tuple[Any, dict[str, Any] | None, Any]:
    """Walk nodes in topological order, executing one at a time.

    In debug mode (``run.run_mode == "debug"``), durably waits for a
    ``workflow-run.{uuid}.step.{node_id}`` event before executing each node —
    this is the "Next Step" gate. In normal mode this behaves exactly like the
    previous ``StepRunner.execute_all`` in-one-shot walk.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the (possibly reloaded, e.g. after a debug resume) WorkflowRun to keep
    using in the caller.
    """
    from services.execution.step_runner import FanOutSignal, StepRunner

    canvas_nodes: list[dict[str, Any]] = wf.canvas_nodes or []
    canvas_edges: list[dict[str, Any]] = wf.canvas_edges or []
    ordered_nodes = runner.build_execution_plan(canvas_nodes, canvas_edges)
    step_results = runner.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

    step_outcomes: dict[str, dict[str, Any]] = {}
    failed = False

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        step_result = step_results[node_id]

        if failed:
            run_repo.update_step_result(step_result, status="skipped")
            continue

        if run.run_mode == "debug":
            node_title = (node.get("data", {}) or {}).get("title", node_id)
            run_repo.update_run_status(
                run,
                status="paused",
                current_node_id=node_id,
                debug_message=(
                    f"Paused before '{node_title}' (node {node_id}). "
                    "Click Next Step to continue."
                ),
            )
            event_key = f"workflow-run.{run.uuid}.step.{node_id}"
            logger.info("Debug pause run_id=%s node_id=%s", run.id, node_id)
            await ctx.aio_wait_for_event(event_key)

            # Force a refresh — a "Run to completion" click (a separate DB
            # session/request) may have flipped run_mode while we waited.
            # A plain re-select would return this same identity-mapped object
            # without re-reading already-loaded columns from the DB.
            run_repo.db.refresh(run)
            if run.run_mode == "debug":
                run_repo.update_run_status(
                    run,
                    status="running",
                    debug_message=f"Resumed. Executing '{node_title}'.",
                )
            else:
                run_repo.update_run_status(run, status="running")

        ok = await runner.execute_one(
            node=node,
            run=run,
            workflow=wf,
            edges=canvas_edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
        )
        if not ok:
            failed = True
            continue

        success_ctx = step_outcomes.get(node_id, {}).get("success")
        if success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled"):
            fan_out_config = dict(success_ctx.metadata["_fan_out"])
            join_node_id = StepRunner._find_join_node_id(node_id, canvas_nodes, canvas_edges)
            logger.info(
                "Fan-out requested node_id=%s mode=%s join_node_id=%s run_id=%s",
                node_id,
                fan_out_config.get("mode"),
                join_node_id,
                run.id,
            )
            signal = FanOutSignal(
                inventory_node_id=node_id,
                fan_out_config=fan_out_config,
                inventory_outcome=success_ctx,
                step_outcomes=dict(step_outcomes),
                join_node_id=join_node_id,
            )
            return (
                None,
                {
                    "signal": signal,
                    "canvas_nodes": canvas_nodes,
                    "canvas_edges": canvas_edges,
                },
                run,
            )

    return ("success" if not failed else "failed"), None, run


@workflow.durable_task(
    name="execute_steps", parents=[prepare], execution_timeout=timedelta(hours=24)
)
async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

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
        final_status, fan_out, run = await _run_steps_until_fan_out_or_done(
            run_repo=run_repo, runner=runner, run=run, wf=wf, ctx=ctx
        )

        if fan_out is None:
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(timezone.utc),
            )
            logger.info("Run finished run_id=%s status=%s", input.run_id, final_status)
            return {"run_id": input.run_id, "status": final_status}

        signal = fan_out["signal"]
        canvas_nodes: list[dict[str, Any]] = fan_out["canvas_nodes"]
        canvas_edges: list[dict[str, Any]] = fan_out["canvas_edges"]

        # Fan-out runs as one atomic step in debug mode: pause once before
        # dispatching children; the join and everything downstream of it then
        # run in a single block on the next step/continue click (no per-device
        # or per-post-join-node pausing — see doc/WORKFLOW-STEPS.md fan-out
        # notes on why children can't be stepped individually).
        if run.run_mode == "debug":
            fan_out_label = signal.join_node_id or signal.inventory_node_id
            run_repo.update_run_status(
                run,
                status="paused",
                current_node_id=fan_out_label,
                debug_message=(
                    "Paused before fan-out dispatch. Click Next Step to run all "
                    "device groups and the fan-in join as one block."
                ),
            )
            event_key = f"workflow-run.{run.uuid}.step.{fan_out_label}"
            logger.info("Debug pause (fan-out) run_id=%s node_id=%s", run.id, fan_out_label)
            await ctx.aio_wait_for_event(event_key)

            run_repo.db.refresh(run)
            run_repo.update_run_status(run, status="running")

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
