from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User


class RunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ─── WorkflowRun ─────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        workflow_id: int,
        triggered_by_id: int,
        trigger_type: str,
        device_ids: list[str],
    ) -> WorkflowRun:
        run = WorkflowRun(
            uuid=str(uuid_mod.uuid4()),
            workflow_id=workflow_id,
            triggered_by_id=triggered_by_id,
            trigger_type=trigger_type,
            device_ids=device_ids,
            status="pending",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run_by_id(self, run_id: int) -> tuple[WorkflowRun, str | None] | None:
        stmt = (
            select(WorkflowRun, User.username.label("triggered_by_username"))
            .outerjoin(User, WorkflowRun.triggered_by_id == User.id)
            .where(WorkflowRun.id == run_id)
        )
        row = self.db.execute(stmt).first()
        if row is None:
            return None
        return (row.WorkflowRun, row.triggered_by_username)

    def get_run_by_uuid(self, run_uuid: str) -> tuple[WorkflowRun, str | None] | None:
        stmt = (
            select(WorkflowRun, User.username.label("triggered_by_username"))
            .outerjoin(User, WorkflowRun.triggered_by_id == User.id)
            .where(WorkflowRun.uuid == run_uuid)
        )
        row = self.db.execute(stmt).first()
        if row is None:
            return None
        return (row.WorkflowRun, row.triggered_by_username)

    def list_runs_for_workflow(
        self, workflow_id: int
    ) -> list[tuple[WorkflowRun, str | None]]:
        stmt = (
            select(WorkflowRun, User.username.label("triggered_by_username"))
            .outerjoin(User, WorkflowRun.triggered_by_id == User.id)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.created_at.desc())
        )
        return [(row.WorkflowRun, row.triggered_by_username) for row in self.db.execute(stmt)]

    def update_run_status(
        self,
        run: WorkflowRun,
        *,
        status: str,
        hatchet_run_id: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowRun:
        run.status = status
        if hatchet_run_id is not None:
            run.hatchet_run_id = hatchet_run_id
        if error_message is not None:
            run.error_message = error_message
        if started_at is not None:
            run.started_at = started_at
        if finished_at is not None:
            run.finished_at = finished_at
        self.db.commit()
        self.db.refresh(run)
        return run

    # ─── WorkflowStepResult ──────────────────────────────────────────────────

    def create_step_result(
        self,
        *,
        run_id: int,
        step_node_id: str,
        step_type: str,
        step_name: str,
    ) -> WorkflowStepResult:
        step_result = WorkflowStepResult(
            run_id=run_id,
            step_node_id=step_node_id,
            step_type=step_type,
            step_name=step_name,
            status="pending",
        )
        self.db.add(step_result)
        self.db.commit()
        self.db.refresh(step_result)
        return step_result

    def update_step_result(
        self,
        step_result: WorkflowStepResult,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowStepResult:
        step_result.status = status
        if output is not None:
            step_result.output = output
        if error_message is not None:
            step_result.error_message = error_message
        if started_at is not None:
            step_result.started_at = started_at
        if finished_at is not None:
            step_result.finished_at = finished_at
        self.db.commit()
        self.db.refresh(step_result)
        return step_result

    def get_step_results_for_run(self, run_id: int) -> list[WorkflowStepResult]:
        stmt = (
            select(WorkflowStepResult)
            .where(WorkflowStepResult.run_id == run_id)
            .order_by(WorkflowStepResult.id)
        )
        return list(self.db.execute(stmt).scalars())
