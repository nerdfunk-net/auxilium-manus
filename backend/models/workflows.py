from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowVisibility = Literal["public", "private"]


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    folder: str | None = Field("/", max_length=500)
    visibility: WorkflowVisibility = "private"
    canvas_nodes: list[dict[str, Any]] = Field(default_factory=list)
    canvas_edges: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    folder: str | None = None
    visibility: WorkflowVisibility | None = None
    canvas_nodes: list[dict[str, Any]] | None = None
    canvas_edges: list[dict[str, Any]] | None = None


class WorkflowSummary(BaseModel):
    id: int
    uuid: str | None
    name: str
    creator_id: int | None
    creator_username: str | None
    description: str | None
    folder: str | None
    visibility: str
    created_at: datetime
    updated_at: datetime


class WorkflowResponse(WorkflowSummary):
    canvas_nodes: list[dict[str, Any]] | None
    canvas_edges: list[dict[str, Any]] | None


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummary]
    total: int


class WorkflowNameCheckResponse(BaseModel):
    available: bool
    message: str | None = None
