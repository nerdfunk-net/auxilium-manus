from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScheduleType = Literal["cron", "once"]


class WorkflowScheduleCreate(BaseModel):
    workflow_id: int
    name: str | None = Field(None, max_length=120)
    schedule_type: ScheduleType
    cron_expression: str | None = None
    run_at: datetime | None = None
    enabled: bool = True
    # Per-schedule static-attribute values (name -> value). Validated against the
    # workflow's static_attributes at save time.
    run_inputs: dict[str, Any] = Field(default_factory=dict)
    # Overlapping-run protection: creating a schedule publishes the workflow to
    # the background tier with this Hatchet concurrency limit. 1 = never run two
    # instances of this workflow at once. None = unlimited.
    concurrency_limit: int | None = Field(default=1, ge=1)


class WorkflowScheduleUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    schedule_type: ScheduleType | None = None
    cron_expression: str | None = None
    run_at: datetime | None = None
    enabled: bool | None = None
    run_inputs: dict[str, Any] | None = None
    concurrency_limit: int | None = Field(default=None, ge=1)


class WorkflowScheduleResponse(BaseModel):
    id: int
    uuid: str
    workflow_id: int
    workflow_name: str | None = None
    name: str | None
    schedule_type: ScheduleType
    cron_expression: str | None
    run_at: datetime | None
    enabled: bool
    run_inputs: dict[str, Any]
    concurrency_limit: int | None = None
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
