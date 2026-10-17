"""Hatchet ``WorkflowExecution`` workflow: prepare -> execute_steps.

Split into a package (2026-09): task wiring + registration live here; the
per-phase implementation lives in sibling modules —
  phase1.py            phase-1 topological walk, debug stepping, early finish
  fan_out_dispatch.py  phase-2 child dispatch (+ Wait & Run batching)
  batch_approval.py    Wait & Run approval-state + gate helpers
  aggregation.py       phase-3/4 child-result merge, persist, post-join resume

Every phase function is the same plain async function it was before the split
(no behaviour change); ``build_workflow_execution`` / ``workflow`` are unchanged
so ``from hatchet.workflows.workflow_run import workflow as workflow_execution``
keeps working for hatchet/worker.py, dynamic_worker.py, dispatch.py,
scheduled_trigger.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from hatchet_sdk import Context, DurableContext
from pydantic import BaseModel

from hatchet.client import hatchet

# Re-exports — keep import paths stable for callers & tests
# (test_wait_and_run_dispatch.py patches ``wf_run_module.child_workflow``;
# test_aggregate_and_persist_final.py imports ``_aggregate_and_persist``;
# test_step_runner_funnel.py / test_step_runner_disabled_steps.py /
# test_step_runner_blocked_by_failure.py / test_execution_characterization.py
# import ``_run_steps_until_fan_out_or_done``).
from hatchet.workflows.device_group_execution import child_workflow  # noqa: F401
from hatchet.workflows.workflow_run.aggregation import (
    _aggregate_and_persist,  # noqa: F401
    _finalize_fan_out_parent,
)
from hatchet.workflows.workflow_run.fan_out_dispatch import _dispatch_children
from hatchet.workflows.workflow_run.phase1 import (
    _phase1_run_or_early_finish,
    _run_steps_until_fan_out_or_done,  # noqa: F401
)

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

logger = logging.getLogger(__name__)


class WorkflowRunInput(BaseModel):
    run_id: int


_INTERRUPTED = (
    "The workflow task ended before the run finished (worker stopped, timeout or engine "
    "cancel). Devices may have been changed by the steps that had started."
)
_DELIVERED_TWICE = (
    "The run was delivered to a worker twice; it was not executed again so that no device "
    "is configured twice."
)
_INTERNAL = "The workflow engine hit an internal error; see the worker log for this error id."


def _finalise_interrupted(run_id: int, message: str) -> None:
    """Sync on purpose: runs inside a cancelled task, where awaiting is unreliable."""
    from core.database import SessionLocal
    from services.execution.run_lifecycle_service import RunLifecycleService

    with SessionLocal() as db:
        RunLifecycleService(db).fail_interrupted(run_id, message=message)


async def prepare(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Preparing workflow run run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        claimed = RunRepository(db).transition_run(
            input.run_id,
            to_status="running",
            from_statuses=("pending",),
            fields={"started_at": datetime.now(UTC)},
        )
    if not claimed:
        # Cancelled while queued, already running, or replayed: never start it twice.
        logger.info("Run not started (not pending) run_id=%s", input.run_id)
    return {"run_id": input.run_id, "claimed": claimed}


async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    """Never leaves the run row open: every exit writes a terminal state (C1-02)."""
    from services.execution.step_runner import RunAlreadyStarted

    try:
        return await _execute_steps(input, ctx)
    except asyncio.CancelledError:
        _finalise_interrupted(input.run_id, _INTERRUPTED)
        raise
    except RunAlreadyStarted:
        _finalise_interrupted(input.run_id, _DELIVERED_TWICE)
        raise
    except Exception:
        # The message is a constant: str(exc) can carry device text or secrets.
        logger.exception("Workflow execution failed run_id=%s", input.run_id)
        _finalise_interrupted(input.run_id, _INTERNAL)
        raise


async def fail_run(input: WorkflowRunInput, ctx: Context) -> dict:
    """Workflow-level on-failure task: covers the 24 h task timeout and a lost worker."""
    _finalise_interrupted(input.run_id, _INTERRUPTED)
    return {"run_id": input.run_id}


async def _execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
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
    # on_failure_task runs when any task fails or times out (e.g. the 24 h limit).
    wf.on_failure_task(name="fail_run", execution_timeout=timedelta(seconds=30))(fail_run)
    return wf


# Static registration — unchanged for every existing importer
# (`from hatchet.workflows.workflow_run import workflow as workflow_execution`).
workflow = build_workflow_execution(name="WorkflowExecution")
