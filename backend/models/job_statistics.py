from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WorkflowVisibility = Literal["public", "private"]


class JobStatisticsSummaryItem(BaseModel):
    workflow_id: int
    workflow_name: str
    workflow_visibility: WorkflowVisibility
    latest_run_id: int
    latest_run_created_at: datetime
    success_count: int
    failed_count: int
    total_count: int


class JobStatisticsSummaryListResponse(BaseModel):
    jobs: list[JobStatisticsSummaryItem]


class JobStatisticsPieResponse(BaseModel):
    workflow_id: int
    workflow_name: str
    run_id: int
    run_created_at: datetime
    success_count: int
    failed_count: int
    total_count: int
