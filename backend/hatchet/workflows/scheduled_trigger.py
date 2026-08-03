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
    from hatchet.workflows.workflow_run import WorkflowRunInput
    from hatchet.workflows.workflow_run import workflow as workflow_execution
    from repositories.run_repository import RunRepository
    from repositories.schedule_repository import ScheduleRepository

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

        run_repo = RunRepository(db)
        run = run_repo.create_run(
            workflow_id=input.workflow_id,
            triggered_by_id=schedule.created_by_id,
            trigger_type="scheduled",
            device_ids=[],
            run_mode="normal",
        )
        ref = workflow_execution.run_no_wait(WorkflowRunInput(run_id=run.id))
        run_repo.update_run_status(
            run, status="pending", hatchet_run_id=str(ref.workflow_run_id or "")
        )

        # A one-time trigger is consumed on fire; a cron keeps repeating.
        schedule_repo.mark_triggered(schedule, disable=(schedule.schedule_type == "once"))

        logger.info(
            "Scheduled trigger dispatched run_id=%s workflow_id=%s schedule_id=%s",
            run.id,
            input.workflow_id,
            input.schedule_id,
        )

    return {"run_id": run.id}
