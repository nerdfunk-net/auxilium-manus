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
    # Things that would run the AI's canvas unattended; the AI write gate refuses while any exist.
    unattended_triggers: list[str] = Field(default_factory=list)
