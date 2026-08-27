"""Wrapper workflow that Hatchet cron/scheduled triggers dispatch into.

`hatchet.cron.create`/`hatchet.scheduled.create` replay a fixed `input` payload
on every fire — they don't call back into the app to mint a fresh WorkflowRun
row first. This workflow is that missing glue: it looks up the WorkflowSchedule
row referenced by its input, creates a new WorkflowRun for the target workflow,
and dispatches it into the normal WorkflowExecution engine exactly like a
manual trigger (RunService.trigger_run) would.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from hatchet_sdk import Context
from pydantic import BaseModel

from hatchet.client import hatchet

logger = logging.getLogger(__name__)


class ScheduledTriggerInput(BaseModel):
    workflow_id: int
    schedule_id: int


workflow = hatchet.workflow(name="ScheduledWorkflowTrigger", input_validator=ScheduledTriggerInput)


@workflow.task(name="dispatch", execution_timeout=timedelta(seconds=30))
async def dispatch(input: ScheduledTriggerInput, ctx: Context) -> dict:
    from core.database import SessionLocal
    from hatchet.workflows.dispatch import resolve_dispatch_workflow
    from hatchet.workflows.workflow_run import WorkflowRunInput
    from hatchet.workflows.workflow_run import workflow as workflow_execution
    from repositories.run_repository import RunRepository
    from repositories.schedule_repository import ScheduleRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.run_input_validation import (
        RunInputValidationError,
        resolve_run_inputs,
    )

    with SessionLocal() as db:
        schedule_repo = ScheduleRepository(db)
        schedule = schedule_repo.get_by_id(input.schedule_id)
        # Guard: the schedule may have been disabled/deleted between the
        # Hatchet trigger firing and this task running (e.g. deleted just
        # before a cron tick) — skip rather than run against a stale config.
        if schedule is None or not schedule.enabled or schedule.workflow_id != input.workflow_id:
            logger.info(
                "Skipping scheduled trigger: schedule_id=%s no longer active", input.schedule_id
            )
            return {"skipped": True}

        wf_result = WorkflowRepository(db).get_by_id(input.workflow_id)
        static_attributes = wf_result[0].static_attributes if wf_result else None

        run_repo = RunRepository(db)
        run = run_repo.create_run(
            workflow_id=input.workflow_id,
            triggered_by_id=schedule.created_by_id,
            trigger_type="scheduled",
            device_ids=[],
            run_mode="normal",
        )

        # A one-time trigger is consumed on fire; a cron keeps repeating —
        # mark it triggered regardless of whether dispatch below succeeds,
        # so a workflow permanently missing a required input doesn't spin.
        schedule_repo.mark_triggered(schedule, disable=(schedule.schedule_type == "once"))

        # Scheduled runs never have an operator to prompt, so only declared
        # defaults are available — a required attribute with no default can
        # never be satisfied here and fails this run immediately rather than
        # dispatching into Hatchet with an incomplete run_input bag.
        try:
            run_inputs = resolve_run_inputs(static_attributes, {})
        except RunInputValidationError as exc:
            run_repo.update_run_status(
                run,
                status="failed",
                error_message=str(exc),
                error_category="configuration",
            )
            logger.info(
                "Scheduled trigger failed run input validation run_id=%s workflow_id=%s "
                "schedule_id=%s error=%s",
                run.id,
                input.workflow_id,
                input.schedule_id,
                exc,
            )
            return {"run_id": run.id, "status": "failed"}

        run.run_inputs = run_inputs
        db.commit()

        dispatch_workflow = (
            resolve_dispatch_workflow(wf_result[0], db) if wf_result else workflow_execution
        )
        ref = dispatch_workflow.run_no_wait(WorkflowRunInput(run_id=run.id))
        run_repo.update_run_status(
            run, status="pending", hatchet_run_id=str(ref.workflow_run_id or "")
        )

        logger.info(
            "Scheduled trigger dispatched run_id=%s workflow_id=%s schedule_id=%s",
            run.id,
            input.workflow_id,
            input.schedule_id,
        )

    return {"run_id": run.id}
