from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from hatchet_sdk import Context, DurableContext
from pydantic import BaseModel

from hatchet.client import hatchet

# Re-exports — keep import paths stable for callers & tests
# (test_wait_and_run_dispatch.py patches ``wf_run_module.child_workflow``;
# test_aggregate_and_persist_final.py imports ``_aggregate_and_persist``).
from hatchet.workflows.device_group_execution import child_workflow  # noqa: F401
from hatchet.workflows.workflow_run.aggregation import (
    _aggregate_and_persist,  # noqa: F401
    _finalize_fan_out_parent,
)
from hatchet.workflows.workflow_run.fan_out_dispatch import _dispatch_children
from services.execution.run_events import (
    STEP_EVENT_LOOKBACK,
    debug_step_event_key,
)

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

logger = logging.getLogger(__name__)


class WorkflowRunInput(BaseModel):
    run_id: int


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
            started_at=datetime.now(UTC),
        )

    return {"run_id": input.run_id}


async def _maybe_debug_pause_before_node(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    node: dict[str, Any],
    ctx: DurableContext,
) -> Any:
    if run.run_mode != "debug":
        return run

    node_id: str = node.get("id", "")
    node_title = (node.get("data", {}) or {}).get("title", node_id)
    run_repo.update_run_status(
        run,
        status="paused",
        current_node_id=node_id,
        debug_message=(
            f"Paused before '{node_title}' (node {node_id}). Click Next Step to continue."
        ),
    )
    event_key = debug_step_event_key(run.uuid, node_id)
    logger.info("Debug pause run_id=%s node_id=%s", run.id, node_id)
    # Devices drop idle SSH long before a debug pause can resume — release
    # live sessions now; the next network step reconnects lazily.
    await runner.suspend_device_sessions()
    await ctx.aio_wait_for_event(
        event_key,
        scope=event_key,
        lookback_window=STEP_EVENT_LOOKBACK,
    )

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
    return run


def _fan_out_context_if_requested(
    *,
    node_id: str,
    step_outcomes: dict[str, dict[str, Any]],
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    run_id: int,
) -> dict[str, Any] | None:
    from services.execution.graph import find_join_node_id
    from services.execution.step_runner import FanOutSignal

    success_ctx = step_outcomes.get(node_id, {}).get("success")
    if not (success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled")):
        return None

    fan_out_config = dict(success_ctx.metadata["_fan_out"])
    join_node_id = find_join_node_id(node_id, canvas_nodes, canvas_edges)
    logger.info(
        "Fan-out requested node_id=%s mode=%s join_node_id=%s run_id=%s",
        node_id,
        fan_out_config.get("mode"),
        join_node_id,
        run_id,
    )
    signal = FanOutSignal(
        inventory_node_id=node_id,
        fan_out_config=fan_out_config,
        inventory_outcome=success_ctx,
        step_outcomes=dict(step_outcomes),
        join_node_id=join_node_id,
    )
    return {
        "signal": signal,
        "canvas_nodes": canvas_nodes,
        "canvas_edges": canvas_edges,
    }


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
    canvas_nodes, canvas_edges = runner.load_execution_graph(wf)
    ordered_nodes = runner.build_execution_plan(canvas_nodes, canvas_edges)
    step_results = runner.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

    step_outcomes: dict[str, dict[str, Any]] = {}
    blocked_nodes: set[str] = set()
    failed = False
    any_reported_failure = False

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        step_result = step_results[node_id]

        if failed:
            run_repo.update_step_result(step_result, status="skipped")
            continue

        run = await _maybe_debug_pause_before_node(
            run_repo=run_repo, runner=runner, run=run, node=node, ctx=ctx
        )

        raised, indicates_failure = await runner.run_node_in_sequence(
            node=node,
            run=run,
            workflow=wf,
            edges=canvas_edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
            blocked_nodes=blocked_nodes,
        )
        if raised:
            failed = True
            continue
        if indicates_failure:
            any_reported_failure = True

        fan_out = _fan_out_context_if_requested(
            node_id=node_id,
            step_outcomes=step_outcomes,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            run_id=run.id,
        )
        if fan_out is not None:
            return None, fan_out, run

    return ("success" if not (failed or any_reported_failure) else "failed"), None, run


async def _debug_pause_before_fan_out(
    *,
    run: Any,
    run_repo: Any,
    signal: Any,
    ctx: DurableContext,
) -> None:
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
    event_key = debug_step_event_key(run.uuid, fan_out_label)
    logger.info("Debug pause (fan-out) run_id=%s node_id=%s", run.id, fan_out_label)
    await ctx.aio_wait_for_event(
        event_key,
        scope=event_key,
        lookback_window=STEP_EVENT_LOOKBACK,
    )

    run_repo.db.refresh(run)
    run_repo.update_run_status(run, status="running")


async def _phase1_run_or_early_finish(
    *,
    run_id: int,
    ctx: DurableContext,
    SessionLocal: Any,
    RunRepository: Any,
    WorkflowRepository: Any,
    StepRunner: Any,
) -> dict[str, Any] | tuple[str, Any, list[dict[str, Any]], list[dict[str, Any]]]:
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {run_id} not found")
        run, _ = run_result
        # Captured now — the phase-1 DB session closes before phase 2 dispatch.
        run_uuid = run.uuid

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        runner = StepRunner(db)
        try:
            final_status, fan_out, run = await _run_steps_until_fan_out_or_done(
                run_repo=run_repo, runner=runner, run=run, wf=wf, ctx=ctx
            )
        finally:
            # Close (not suspend) here: on the fan-out path, children build their
            # own pools and phase 2/3 hold no device connections — this also runs
            # before the fan-out debug pause below.
            await runner.close_device_sessions()

        if fan_out is None:
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(UTC),
            )
            logger.info("Run finished run_id=%s status=%s", run_id, final_status)
            return {"run_id": run_id, "status": final_status}

        signal = fan_out["signal"]
        canvas_nodes: list[dict[str, Any]] = fan_out["canvas_nodes"]
        canvas_edges: list[dict[str, Any]] = fan_out["canvas_edges"]

        # Fan-out runs as one atomic step in debug mode: pause once before
        # dispatching children; the join and everything downstream of it then
        # run in a single block on the next step/continue click (no per-device
        # or per-post-join-node pausing — see doc/WORKFLOW-STEPS.md fan-out
        # notes on why children can't be stepped individually).
        if run.run_mode == "debug":
            await _debug_pause_before_fan_out(
                run=run,
                run_repo=run_repo,
                signal=signal,
                ctx=ctx,
            )

    return run_uuid, signal, canvas_nodes, canvas_edges


async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    early = await _phase1_run_or_early_finish(
        run_id=input.run_id,
        ctx=ctx,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    if isinstance(early, dict):
        return early

    run_uuid, signal, canvas_nodes, canvas_edges = early

    logger.info(
        "Fan-out started run_id=%s mode=%s max_concurrency=%s",
        input.run_id,
        signal.fan_out_config.get("mode"),
        signal.fan_out_config.get("max_concurrency"),
    )
    child_results = await _dispatch_children(
        signal,
        input.run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
    )

    final_status = await _finalize_fan_out_parent(
        run_id=input.run_id,
        signal=signal,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
        child_results=child_results,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    logger.info("Run finished (fan-out) run_id=%s status=%s", input.run_id, final_status)
    return {"run_id": input.run_id, "status": final_status}


def build_workflow_execution(
    *, name: str, concurrency: int | None = None
) -> HatchetWorkflow[WorkflowRunInput]:
    """Construct one Hatchet workflow with the standard prepare -> execute_steps
    shape, attaching the shared task implementations above. Used both for the
    single static WorkflowExecution registration below and, per published
    background-tier row, by hatchet/dynamic_worker.py — zero duplicated
    business logic either way, since prepare/execute_steps here are the same
    plain async functions in both cases, just registered under a different
    workflow name/concurrency limit.
    """
    wf = hatchet.workflow(
        name=name,
        on_events=["workflow:run"] if name == "WorkflowExecution" else None,
        input_validator=WorkflowRunInput,
        concurrency=concurrency,
    )
    prepare_task = wf.task(name="prepare", execution_timeout=timedelta(seconds=30))(prepare)
    wf.durable_task(
        name="execute_steps", parents=[prepare_task], execution_timeout=timedelta(hours=24)
    )(execute_steps)
    return wf


# Static registration — unchanged for every existing importer
# (`from hatchet.workflows.workflow_run import workflow as workflow_execution`).
workflow = build_workflow_execution(name="WorkflowExecution")

