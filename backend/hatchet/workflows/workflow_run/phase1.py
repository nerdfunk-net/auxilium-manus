"""Phase 1 of a workflow run: walk the canvas in topological order executing
one node at a time, and stop either at a terminal status or at the first
inventory step that requests fan-out.

Split out of workflow_run; every function is the same plain async function it
was before the split. ``_phase1_run_or_early_finish`` keeps its
injected-dependency signature (``SessionLocal=…, RunRepository=…, …``).

``_run_steps_until_fan_out_or_done`` is a thin adapter around
``StepRunner.execute_all`` — the single canonical phase-1 walk. It used to
reimplement that walk loop independently (see doc/plans/PARALLEL_EXEC.md,
"worth deduplicating"); it now just translates ``execute_all``'s
``bool | FanOutSignal`` return into the ``(status, fan_out_context, run)``
tuple this module's callers and tests expect.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from hatchet_sdk import DurableContext

from services.execution.step_runner import FanOutSignal

logger = logging.getLogger(__name__)


async def _run_steps_until_fan_out_or_done(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    wf: Any,
    ctx: DurableContext,
) -> tuple[Any, dict[str, Any] | None, Any]:
    """Walk nodes in topological order, executing one at a time, via
    ``StepRunner.execute_all``.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the WorkflowRun to keep using in the caller.
    """
    result = await runner.execute_all(run=run, workflow=wf)

    if isinstance(result, FanOutSignal):
        canvas_nodes, canvas_edges = runner.load_execution_graph(wf)
        return (
            None,
            {"signal": result, "canvas_nodes": canvas_nodes, "canvas_edges": canvas_edges},
            run,
        )

    return ("success" if result else "failed"), None, run


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
