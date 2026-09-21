"""Phase 1 of a workflow run: walk the canvas in topological order executing
one node at a time, and stop either at a terminal status or at the first
inventory step that requests fan-out.

Split out of workflow_run; every function is the same plain async function it
was before the split. ``_phase1_run_or_early_finish`` keeps its
injected-dependency signature (``SessionLocal=…, RunRepository=…, …``); the
lazy in-function imports in ``_fan_out_context_if_requested`` are deliberate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from hatchet_sdk import DurableContext

logger = logging.getLogger(__name__)


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

    Behaves exactly like ``StepRunner.execute_all``'s in-one-shot walk.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the WorkflowRun to keep using in the caller.
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
            from services.change_requests.change_request_service import (
                maybe_reconcile_deploy_run,
            )

            maybe_reconcile_deploy_run(db, run)
            logger.info("Run finished run_id=%s status=%s", run_id, final_status)
            return {"run_id": run_id, "status": final_status}

        signal = fan_out["signal"]
        canvas_nodes: list[dict[str, Any]] = fan_out["canvas_nodes"]
        canvas_edges: list[dict[str, Any]] = fan_out["canvas_edges"]

    return run_uuid, signal, canvas_nodes, canvas_edges
