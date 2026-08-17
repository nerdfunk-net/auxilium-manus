from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.models.schedules import WorkflowSchedule
from core.models.workflows import Workflow


class ScheduleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_workflow_id(self, workflow_id: int) -> WorkflowSchedule | None:
        stmt = select(WorkflowSchedule).where(WorkflowSchedule.workflow_id == workflow_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_enabled_with_workflow(
        self, user_id: int
    ) -> list[tuple[WorkflowSchedule, str, str]]:
        stmt = (
            select(
                WorkflowSchedule,
                Workflow.name.label("workflow_name"),
                Workflow.visibility.label("workflow_visibility"),
            )
            .join(Workflow, WorkflowSchedule.workflow_id == Workflow.id)
            .where(
                WorkflowSchedule.enabled.is_(True),
                or_(Workflow.visibility == "public", Workflow.creator_id == user_id),
            )
        )
        return [
            (row.WorkflowSchedule, row.workflow_name, row.workflow_visibility)
            for row in self.db.execute(stmt)
        ]

    def get_by_id(self, schedule_id: int) -> WorkflowSchedule | None:
        return self.db.get(WorkflowSchedule, schedule_id)

    def upsert(
        self,
        workflow_id: int,
        *,
        created_by_id: int | None,
        schedule_type: str,
        cron_expression: str | None,
        run_at: datetime | None,
        enabled: bool,
    ) -> WorkflowSchedule:
        schedule = self.get_by_workflow_id(workflow_id)
        if schedule is None:
            schedule = WorkflowSchedule(
                uuid=str(uuid_mod.uuid4()),
                workflow_id=workflow_id,
                created_by_id=created_by_id,
            )
            self.db.add(schedule)

        schedule.schedule_type = schedule_type
        schedule.cron_expression = cron_expression
        schedule.run_at = run_at
        schedule.enabled = enabled
        schedule.hatchet_cron_id = None
        schedule.hatchet_scheduled_id = None
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def set_hatchet_ids(
        self,
        schedule: WorkflowSchedule,
        *,
        hatchet_cron_id: str | None = None,
        hatchet_scheduled_id: str | None = None,
    ) -> WorkflowSchedule:
        schedule.hatchet_cron_id = hatchet_cron_id
        schedule.hatchet_scheduled_id = hatchet_scheduled_id
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def mark_triggered(self, schedule: WorkflowSchedule, *, disable: bool) -> WorkflowSchedule:
        schedule.last_triggered_at = datetime.now(UTC)
        if disable:
            schedule.enabled = False
            schedule.hatchet_cron_id = None
            schedule.hatchet_scheduled_id = None
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def delete(self, schedule: WorkflowSchedule) -> None:
        self.db.delete(schedule)
        self.db.commit()
