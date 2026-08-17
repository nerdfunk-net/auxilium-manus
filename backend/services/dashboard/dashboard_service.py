from __future__ import annotations

import logging
from datetime import UTC, datetime

from croniter import CroniterError, croniter
from sqlalchemy.orm import Session

from core.models.schedules import WorkflowSchedule
from models.dashboard import (
    DashboardRecentRunsResponse,
    DashboardRunItem,
    DashboardScheduleItem,
    DashboardScheduleListResponse,
)
from repositories.run_repository import RunRepository
from repositories.schedule_repository import ScheduleRepository

logger = logging.getLogger(__name__)

DEFAULT_RECENT_RUNS_LIMIT = 20


def _compute_next_run(schedule: WorkflowSchedule) -> datetime | None:
    if schedule.schedule_type == "once":
        return schedule.run_at

    if not schedule.cron_expression:
        return None

    now = datetime.now(UTC)
    base = schedule.last_triggered_at or now
    try:
        itr = croniter(schedule.cron_expression, base)
        next_run = itr.get_next(datetime)
        while next_run <= now:
            next_run = itr.get_next(datetime)
    except (CroniterError, ValueError, TypeError):
        logger.warning(
            "Failed to compute next run for schedule_id=%s cron_expression=%r",
            schedule.id,
            schedule.cron_expression,
        )
        return None
    return next_run


class DashboardService:
    def __init__(self, db: Session) -> None:
        self._schedule_repo = ScheduleRepository(db)
        self._run_repo = RunRepository(db)

    def list_schedules(self, user_id: int) -> DashboardScheduleListResponse:
        rows = self._schedule_repo.list_enabled_with_workflow(user_id)
        items = [
            DashboardScheduleItem(
                schedule_id=schedule.id,
                workflow_id=schedule.workflow_id,
                workflow_name=workflow_name,
                workflow_visibility=workflow_visibility,
                schedule_type=schedule.schedule_type,
                cron_expression=schedule.cron_expression,
                run_at=schedule.run_at,
                next_run_at=_compute_next_run(schedule),
                last_triggered_at=schedule.last_triggered_at,
            )
            for schedule, workflow_name, workflow_visibility in rows
        ]
        items.sort(key=lambda item: (item.next_run_at is None, item.next_run_at))
        return DashboardScheduleListResponse(schedules=items)

    def list_recent_runs(
        self, user_id: int, *, limit: int = DEFAULT_RECENT_RUNS_LIMIT
    ) -> DashboardRecentRunsResponse:
        rows = self._run_repo.list_recent_runs(user_id, limit=limit)
        items = [
            DashboardRunItem(
                run_id=run.id,
                workflow_id=run.workflow_id,
                workflow_name=workflow_name,
                status=run.status,
                trigger_type=run.trigger_type,
                triggered_by_username=triggered_by_username,
                started_at=run.started_at,
                finished_at=run.finished_at,
                created_at=run.created_at,
            )
            for run, triggered_by_username, workflow_name in rows
        ]
        return DashboardRecentRunsResponse(runs=items)
