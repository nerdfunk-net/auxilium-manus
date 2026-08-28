from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowVisibility = Literal["public", "private"]
StaticAttributeType = Literal["string", "number", "boolean"]


class StaticAttributeDef(BaseModel):
    """One run-scoped trigger input the operator supplies when starting a run
    manually. Resolved values are seeded into every device's attribute_bags
    under the reserved "run_input" bag — see
    services/execution/run_input_validation.py and
    services/workflow_context/run_inputs.py."""

    name: str = Field(..., min_length=1, max_length=100)
    type: StaticAttributeType
    default: Any | None = None
    required: bool = False


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    folder: str | None = Field("/", max_length=500)
    visibility: WorkflowVisibility = "private"
    canvas_nodes: list[dict[str, Any]] = Field(default_factory=list)
    canvas_edges: list[dict[str, Any]] = Field(default_factory=list)
    canvas_groups: list[dict[str, Any]] = Field(default_factory=list)
    static_attributes: list[StaticAttributeDef] = Field(default_factory=list)
    is_version_controlled: bool = False


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    folder: str | None = None
    visibility: WorkflowVisibility | None = None
    canvas_nodes: list[dict[str, Any]] | None = None
    canvas_edges: list[dict[str, Any]] | None = None
    canvas_groups: list[dict[str, Any]] | None = None
    static_attributes: list[StaticAttributeDef] | None = None
    is_version_controlled: bool | None = None


class WorkflowSummary(BaseModel):
    id: int
    uuid: str | None
    name: str
    creator_id: int | None
    creator_username: str | None
    description: str | None
    folder: str | None
    visibility: str
    is_version_controlled: bool
    created_at: datetime
    updated_at: datetime


class WorkflowGitSyncStatus(BaseModel):
    """Outcome of the best-effort Git sync performed as part of a save.

    Git is a backup/history layer, not a transactional partner for the DB
    save — this is always reported, never raised as an error response.
    """

    status: Literal["ok", "failed", "skipped"]
    commit_sha: str | None = None
    pushed: bool = False
    message: str | None = None


class WorkflowResponse(WorkflowSummary):
    canvas_nodes: list[dict[str, Any]] | None
    canvas_edges: list[dict[str, Any]] | None
    canvas_groups: list[dict[str, Any]] | None
    static_attributes: list[StaticAttributeDef] | None
    git_sync: WorkflowGitSyncStatus | None = None


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummary]
    total: int


class WorkflowNameCheckResponse(BaseModel):
    available: bool
    message: str | None = None
    existing_id: int | None = None


class WorkflowGitCommitEntry(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: dict[str, str]
    date: str
    change_type: str | None = None


class WorkflowGitHistoryResponse(BaseModel):
    commits: list[WorkflowGitCommitEntry]
    repository_name: str


class WorkflowGitDiffRequest(BaseModel):
    commit_a: str = Field(..., min_length=4)
    commit_b: str = Field(..., min_length=4)


class WorkflowGitDiffResponse(BaseModel):
    diff_lines: list[str]
    left_lines: list[dict[str, Any]]
    right_lines: list[dict[str, Any]]
    stats: dict[str, int]


class WorkflowGitRestoreRequest(BaseModel):
    commit_sha: str = Field(..., min_length=4)
