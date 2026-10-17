from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WorkflowChangeAction = Literal["created", "updated"]


class WorkflowChangeResponse(BaseModel):
    id: int
    actor_id: int | None
    actor_username: str | None
    action: WorkflowChangeAction
    commit_sha: str | None
    parent_commit_sha: str | None
    has_diff: bool
    created_at: datetime


class WorkflowChangeListResponse(BaseModel):
    changes: list[WorkflowChangeResponse]
