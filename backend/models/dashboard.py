from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from models.schedules import ScheduleType

WorkflowVisibility = Literal["public", "private"]


class DashboardScheduleItem(BaseModel):
    schedule_id: int
    workflow_id: int
    workflow_name: str
    workflow_visibility: WorkflowVisibility
    schedule_type: ScheduleType
    cron_expression: str | None
    run_at: datetime | None
    next_run_at: datetime | None
    last_triggered_at: datetime | None


class DashboardScheduleListResponse(BaseModel):
    schedules: list[DashboardScheduleItem]


class DashboardRunItem(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str
    status: str
    trigger_type: str
    triggered_by_username: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class DashboardRecentRunsResponse(BaseModel):
    runs: list[DashboardRunItem]
