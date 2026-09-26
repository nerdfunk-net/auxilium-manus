from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WorkflowAiSessionEnableRequest(BaseModel):
    ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)


class WorkflowAiSessionResponse(BaseModel):
    active: bool
    expires_at: datetime | None
    enabled_by_username: str | None
    workflow_updated_at: datetime
