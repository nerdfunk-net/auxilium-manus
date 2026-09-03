from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.models.schedules import WorkflowSchedule
from core.models.workflows import Workflow


class ScheduleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, schedule_id: int) -> WorkflowSchedule | None:
        return self.db.get(WorkflowSchedule, schedule_id)

    def list_by_workflow_id(self, workflow_id: int) -> list[WorkflowSchedule]:
        stmt = (
            select(WorkflowSchedule)
            .where(WorkflowSchedule.workflow_id == workflow_id)
            .order_by(WorkflowSchedule.id.asc())
        )
        return list(self.db.execute(stmt).scalars())

    def list_visible(
        self, user_id: int, workflow_id: int | None = None
    ) -> list[tuple[WorkflowSchedule, str]]:
        """Every schedule on a workflow the user may see (public, or their own
        private), newest first. Returns (schedule, workflow_name) pairs."""
        stmt = (
            select(WorkflowSchedule, Workflow.name.label("workflow_name"))
            .join(Workflow, WorkflowSchedule.workflow_id == Workflow.id)
            .where(or_(Workflow.visibility == "public", Workflow.creator_id == user_id))
            .order_by(WorkflowSchedule.created_at.desc(), WorkflowSchedule.id.desc())
        )
        if workflow_id is not None:
            stmt = stmt.where(WorkflowSchedule.workflow_id == workflow_id)
        return [(row.WorkflowSchedule, row.workflow_name) for row in self.db.execute(stmt)]

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

    def create(
        self,
        workflow_id: int,
        *,
        created_by_id: int | None,
        name: str | None,
        schedule_type: str,
        cron_expression: str | None,
        run_at: datetime | None,
        enabled: bool,
        run_inputs: dict[str, Any],
    ) -> WorkflowSchedule:
        schedule = WorkflowSchedule(
            uuid=str(uuid_mod.uuid4()),
            workflow_id=workflow_id,
            created_by_id=created_by_id,
            name=name,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            run_at=run_at,
            enabled=enabled,
            run_inputs=run_inputs,
        )
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def update(self, schedule: WorkflowSchedule, **fields: Any) -> WorkflowSchedule:
        for key, value in fields.items():
            setattr(schedule, key, value)
        # A schedule edit always re-registers with Hatchet — clear stale ids.
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
