from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ScheduleType = Literal["cron", "once"]


class WorkflowScheduleUpsert(BaseModel):
    schedule_type: ScheduleType
    cron_expression: str | None = None
    run_at: datetime | None = None
    enabled: bool = True


class WorkflowScheduleResponse(BaseModel):
    id: int
    uuid: str
    workflow_id: int
    schedule_type: ScheduleType
    cron_expression: str | None
    run_at: datetime | None
    enabled: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
