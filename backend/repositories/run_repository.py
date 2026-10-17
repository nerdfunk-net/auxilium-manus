from __future__ import annotations

import logging
import uuid as uuid_mod
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.runs import TERMINAL_RUN_STATUSES

logger = logging.getLogger(__name__)

_STEP_ROW_MESSAGE_MAX = 4000
_ACTIVE_RUN_STATUSES = ("pending", "running", "paused")
_TERMINAL_STEP_STATUSES = ("success", "failed", "skipped")


class StepResultExistsError(RuntimeError):
    """A step row for this (run, node) already exists: another delivery is walking the run."""


class RunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ─── WorkflowRun ─────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        workflow_id: int,
        triggered_by_id: int | None,
        trigger_type: str,
        device_ids: list[str],
        run_inputs: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        run = WorkflowRun(
            uuid=str(uuid_mod.uuid4()),
            workflow_id=workflow_id,
            triggered_by_id=triggered_by_id,
            trigger_type=trigger_type,
            device_ids=device_ids,
            status="pending",
            run_inputs=run_inputs or {},
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

    def list_runs_for_workflow(
        self,
        workflow_id: int,
        *,
        statuses: list[str] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[WorkflowRun, str | None]], int]:
        """One page of a workflow's runs (newest first) and the total number of matches."""
        base = select(WorkflowRun.id).where(WorkflowRun.workflow_id == workflow_id)

        if statuses:
            run_statuses = [s for s in statuses if s != "skipped"]
            include_skipped_steps = "skipped" in statuses
            status_conditions = []
            if run_statuses:
                status_conditions.append(WorkflowRun.status.in_(run_statuses))
            if include_skipped_steps:
                status_conditions.append(
                    exists(
                        select(1).where(
                            WorkflowStepResult.run_id == WorkflowRun.id,
                            WorkflowStepResult.status == "skipped",
                        )
                    )
                )
            if len(status_conditions) == 1:
                base = base.where(status_conditions[0])
            elif len(status_conditions) > 1:
                base = base.where(or_(*status_conditions))

        if created_from is not None:
            base = base.where(WorkflowRun.created_at >= created_from)
        if created_to is not None:
            base = base.where(WorkflowRun.created_at <= created_to)

        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        page_ids = (
            base.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = (
            select(WorkflowRun, User.username.label("triggered_by_username"))
            .outerjoin(User, WorkflowRun.triggered_by_id == User.id)
            .where(WorkflowRun.id.in_(page_ids))
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        )
        rows = [(row.WorkflowRun, row.triggered_by_username) for row in self.db.execute(stmt)]
        return rows, int(total)

    def list_recent_runs(
        self, user_id: int, *, limit: int
    ) -> list[tuple[WorkflowRun, str | None, str]]:
        stmt = (
            select(
                WorkflowRun,
                User.username.label("triggered_by_username"),
                Workflow.name.label("workflow_name"),
            )
            .join(Workflow, WorkflowRun.workflow_id == Workflow.id)
            .outerjoin(User, WorkflowRun.triggered_by_id == User.id)
            .where(or_(Workflow.visibility == "public", Workflow.creator_id == user_id))
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        )
        return [
            (row.WorkflowRun, row.triggered_by_username, row.workflow_name)
            for row in self.db.execute(stmt)
        ]

    def transition_run(
        self,
        run_id: int,
        *,
        to_status: str,
        from_statuses: Collection[str] | None = None,
        fields: Mapping[str, Any] | None = None,
    ) -> bool:
        """Atomically move a run; True when *this* call changed the row.

        Without ``from_statuses`` the guard is "not terminal": a run that is already
        success/failed/cancelled is never changed again, so a worker that finishes after the
        operator cancelled cannot turn ``cancelled`` back into ``success`` (C1-03).
        """
        guard = (
            WorkflowRun.status.in_(tuple(from_statuses))
            if from_statuses is not None
            else WorkflowRun.status.not_in(tuple(TERMINAL_RUN_STATUSES))
        )
        values: dict[str, Any] = {**(fields or {}), "status": to_status}
        if to_status in TERMINAL_RUN_STATUSES:
            values.update(current_node_id=None, approval_state=None)
        result = cast(
            CursorResult,
            self.db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, guard)
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        self.db.commit()
        return result.rowcount == 1

    def update_run_status(
        self,
        run: WorkflowRun,
        *,
        status: str,
        hatchet_run_id: str | None = None,
        error_message: str | None = None,
        error_category: str | None = None,
        error_id: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        current_node_id: str | None = None,
        debug_message: str | None = None,
        approval_state: dict[str, Any] | None = None,
        clear_approval_state: bool = False,
    ) -> WorkflowRun:
        candidates = {
            "hatchet_run_id": hatchet_run_id,
            "error_message": error_message,
            "error_category": error_category,
            "error_id": error_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "current_node_id": current_node_id,
            "debug_message": debug_message,
            "approval_state": approval_state,
        }
        fields: dict[str, Any] = {k: v for k, v in candidates.items() if v is not None}
        if approval_state is None and clear_approval_state:
            fields["approval_state"] = None
        changed = self.transition_run(run.id, to_status=status, fields=fields)
        self.db.refresh(run)  # the other writer may have won; callers keep using the real row
        if not changed:
            logger.info(
                "run_id=%s status update to %r refused: run is already %s",
                run.id,
                status,
                run.status,
            )
        return run

    def finalise_open_step_results(self, run_id: int, *, message: str) -> None:
        """A run ended without its steps being closed (crash, cancel): ``running`` rows become
        ``failed`` with *message*, ``pending`` rows become ``skipped``."""
        now = datetime.now(UTC)
        base = update(WorkflowStepResult).where(WorkflowStepResult.run_id == run_id)
        self.db.execute(
            base.where(WorkflowStepResult.status == "running").values(
                status="failed",
                error_message=message[:_STEP_ROW_MESSAGE_MAX],
                error_category="internal",
                finished_at=now,
            )
        )
        self.db.execute(
            base.where(WorkflowStepResult.status == "pending").values(
                status="skipped", finished_at=now
            )
        )
        self.db.commit()

    def has_active_runs(self, workflow_id: int) -> bool:
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        WorkflowRun.workflow_id == workflow_id,
                        WorkflowRun.status.in_(_ACTIVE_RUN_STATUSES),
                    )
                )
            )
        )

    def list_active_run_ids(self) -> set[int]:
        """Ids of every run that is still pending, running or paused."""
        stmt = select(WorkflowRun.id).where(WorkflowRun.status.in_(_ACTIVE_RUN_STATUSES))
        return set(self.db.scalars(stmt))

    def list_active_runs_older_than(self, cutoff: datetime) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).where(
            WorkflowRun.status.in_(_ACTIVE_RUN_STATUSES), WorkflowRun.created_at < cutoff
        )
        return list(self.db.scalars(stmt))

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
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise StepResultExistsError(
                f"run {run_id} already has a step result for node {step_node_id}"
            ) from exc
        self.db.refresh(step_result)
        return step_result

    def update_step_result(
        self,
        step_result: WorkflowStepResult,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
        error_category: str | None = None,
        error_id: str | None = None,
        failure: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowStepResult:
        candidates = {
            "output": output,
            "error_message": error_message,
            "error_category": error_category,
            "error_id": error_id,
            "failure": failure,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        values: dict[str, Any] = {k: v for k, v in candidates.items() if v is not None}
        values["status"] = status
        # A cancel closes the open step rows; a step that was already executing must not
        # reopen its row afterwards (the run stays cancelled, so the history must agree).
        cancelled_run = select(WorkflowRun.id).where(
            WorkflowRun.id == step_result.run_id, WorkflowRun.status == "cancelled"
        )
        applied = cast(
            CursorResult,
            self.db.execute(
                update(WorkflowStepResult)
                .where(
                    WorkflowStepResult.id == step_result.id,
                    ~(
                        WorkflowStepResult.status.in_(_TERMINAL_STEP_STATUSES)
                        & WorkflowStepResult.run_id.in_(cancelled_run)
                    ),
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        self.db.commit()
        if applied.rowcount != 1:
            logger.info(
                "Step result left as is: run cancelled run_id=%s node_id=%s ignored_status=%s",
                step_result.run_id,
                step_result.step_node_id,
                status,
            )
        self.db.refresh(step_result)
        return step_result

    def get_step_results_for_run(self, run_id: int) -> list[WorkflowStepResult]:
        stmt = (
            select(WorkflowStepResult)
            .where(WorkflowStepResult.run_id == run_id)
            .order_by(WorkflowStepResult.id)
        )
        return list(self.db.execute(stmt).scalars())

    def get_step_progress_rows(self, run_id: int) -> list[Any]:
        """Light step rows (no ``output`` column) for the progress poll."""
        stmt = (
            select(
                WorkflowStepResult.step_node_id,
                WorkflowStepResult.status,
                WorkflowStepResult.started_at,
                WorkflowStepResult.finished_at,
                WorkflowStepResult.error_message,
            )
            .where(WorkflowStepResult.run_id == run_id)
            .order_by(WorkflowStepResult.id)
        )
        return list(self.db.execute(stmt))

    # ─── WorkflowRunDeviceGroup (fan-out child progress) ─────────────────────

    def _get_device_group(self, run_id: int, child_index: int) -> WorkflowRunDeviceGroup | None:
        stmt = select(WorkflowRunDeviceGroup).where(
            WorkflowRunDeviceGroup.run_id == run_id,
            WorkflowRunDeviceGroup.child_index == child_index,
        )
        return self.db.execute(stmt).scalars().first()

    def create_device_groups(self, *, run_id: int, groups: list[tuple[int, list[str]]]) -> None:
        """Pre-create one ``pending`` row per ``(child_index, device_names)``.

        Idempotent: groups that already exist keep their current progress.
        """
        existing = {g.child_index for g in self.list_device_groups(run_id)}
        for child_index, device_names in groups:
            if child_index in existing:
                continue
            self.db.add(
                WorkflowRunDeviceGroup(
                    run_id=run_id,
                    child_index=child_index,
                    device_names=list(device_names),
                    status="pending",
                    node_states={},
                )
            )
        self.db.commit()

    def mark_device_group_started(self, *, run_id: int, child_index: int) -> None:
        group = self._get_device_group(run_id, child_index)
        if group is None:
            return
        group.status = "running"
        group.started_at = datetime.now(UTC)
        self.db.commit()

    def set_device_group_node_state(
        self, *, run_id: int, child_index: int, node_id: str, state: str
    ) -> None:
        group = self._get_device_group(run_id, child_index)
        if group is None:
            return
        # New dict, not in-place mutation: JSON columns don't track mutations.
        group.node_states = {**(group.node_states or {}), node_id: state}
        self.db.commit()

    def finish_device_group(
        self,
        *,
        run_id: int,
        child_index: int,
        status: str,
        error_message: str | None = None,
    ) -> None:
        group = self._get_device_group(run_id, child_index)
        if group is None:
            return
        group.status = status
        if error_message is not None:
            group.error_message = error_message
        group.finished_at = datetime.now(UTC)
        self.db.commit()

    def list_device_groups(self, run_id: int) -> list[WorkflowRunDeviceGroup]:
        stmt = (
            select(WorkflowRunDeviceGroup)
            .where(WorkflowRunDeviceGroup.run_id == run_id)
            .order_by(WorkflowRunDeviceGroup.child_index)
        )
        return list(self.db.execute(stmt).scalars())

    def delete_run(self, run: WorkflowRun) -> None:
        """Delete a single run. Step results cascade via ON DELETE CASCADE."""
        self.db.delete(run)
        self.db.commit()

    def list_uuids_for_workflow(self, workflow_id: int) -> list[str]:
        return list(
            self.db.scalars(select(WorkflowRun.uuid).where(WorkflowRun.workflow_id == workflow_id))
        )

    def list_all_uuids(self) -> set[str]:
        return set(self.db.scalars(select(WorkflowRun.uuid)))

    def _finished_runs_older_than_filter(self, *, cutoff: datetime):
        return (
            WorkflowRun.status.in_(TERMINAL_RUN_STATUSES),
            WorkflowRun.created_at < cutoff,
        )

    def count_finished_runs_older_than(self, *, cutoff: datetime) -> int:
        status_filter, created_filter = self._finished_runs_older_than_filter(cutoff=cutoff)
        stmt = select(func.count()).select_from(WorkflowRun).where(status_filter, created_filter)
        return int(self.db.scalar(stmt) or 0)

    def purge_finished_runs_older_than(
        self,
        *,
        cutoff: datetime,
        batch_size: int = 500,
    ) -> int:
        """Delete finished runs before cutoff. Step results cascade on delete."""
        total_deleted = 0
        status_filter, created_filter = self._finished_runs_older_than_filter(cutoff=cutoff)

        while True:
            id_stmt = (
                select(WorkflowRun.id)
                .where(status_filter, created_filter)
                .order_by(WorkflowRun.id)
                .limit(batch_size)
            )
            run_ids = list(self.db.scalars(id_stmt))
            if not run_ids:
                break

            result = self.db.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(run_ids)))
            self.db.commit()
            total_deleted += cast(CursorResult, result).rowcount or 0

        return total_deleted
