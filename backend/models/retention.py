from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WorkflowRunRetentionResult(BaseModel):
    dry_run: bool
    retention_days: int
    cutoff: datetime
    runs_deleted: int
