"""Wrapper workflow that Hatchet cron/scheduled triggers dispatch into.

`hatchet.cron.create`/`hatchet.scheduled.create` replay a fixed `input` payload
on every fire — they don't call back into the app to mint a fresh WorkflowRun
row first. This workflow is that missing glue: it looks up the WorkflowSchedule
row referenced by its input, creates a new WorkflowRun for the target workflow,
and starts it via services.execution.schedule_fire.start_scheduled_run (shared with the
"Run now" button).
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
    from core.config import settings
    from core.database import SessionLocal
    from repositories.plugin_repository import PluginRepository
    from repositories.schedule_repository import ScheduleRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.schedule_fire import start_scheduled_run
    from services.plugin_registry.plugin_registry_service import PluginRegistryService

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

        # Re-validated on every fire (S2-04): the creator must still be active, still hold
        # workflows:execute, and still be able to see the workflow. Otherwise the schedule is
        # switched off instead of running with rights its creator no longer has.
        from repositories.user_repository import UserRepository
        from services.auth.rbac_service import RBACService

        owner = (
            UserRepository(db).get_by_id(schedule.created_by_id) if schedule.created_by_id else None
        )
        workflow_row = wf_result[0] if wf_result is not None else None
        authorised = (
            owner is not None
            and owner.is_active
            and RBACService(db).has_permission(owner.id, "workflows", "execute")
            and workflow_row is not None
            and not (workflow_row.visibility == "private" and workflow_row.creator_id != owner.id)
        )
        if not authorised or workflow_row is None:
            schedule_repo.update(schedule, enabled=False)
            logger.warning(
                "Schedule %s disabled: its creator is no longer allowed to run workflow %s",
                schedule.id,
                input.workflow_id,
            )
            return {"skipped": True, "reason": "creator_not_authorised"}

        # A one-time trigger is consumed on fire; a cron keeps repeating — mark it
        # triggered regardless of whether the run below starts, so a workflow permanently
        # missing a required input doesn't spin.
        schedule_repo.mark_triggered(schedule, disable=(schedule.schedule_type == "once"))

        run = start_scheduled_run(
            db,
            schedule,
            workflow_row,
            acting_user_id=schedule.created_by_id,
            plugin_registry_service=PluginRegistryService(
                PluginRepository(plugins_file=settings.plugins_file)
            ),
        )
        if run.status == "failed":
            return {"run_id": run.id, "status": "failed"}

    return {"run_id": run.id}
