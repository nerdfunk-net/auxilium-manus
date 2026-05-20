from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

RunStatus = Literal["pending", "running", "success", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "success", "failed", "skipped"]
TriggerType = Literal["manual", "scheduled", "webhook"]


class WorkflowRunCreate(BaseModel):
    device_ids: list[str] = []
    trigger_type: TriggerType = "manual"


class WorkflowStepResultResponse(BaseModel):
    id: int
    run_id: int
    step_node_id: str
    step_type: str
    step_name: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    output: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunSummary(BaseModel):
    id: int
    uuid: str
    workflow_id: int
    triggered_by_id: int | None
    triggered_by_username: str | None
    status: str
    trigger_type: str
    device_ids: list[str] | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunResponse(WorkflowRunSummary):
    hatchet_run_id: str | None
    error_message: str | None
    step_results: list[WorkflowStepResultResponse] = []


class WorkflowRunListResponse(BaseModel):
    runs: list[WorkflowRunSummary]
    total: int
