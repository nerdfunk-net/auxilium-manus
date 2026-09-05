from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

WorkflowVisibility = Literal["public", "private"]
StaticAttributeType = Literal["string", "number", "boolean", "reference"]
# Kinds a `type == "reference"` attribute may point at. Registry-driven — the
# authoritative resolver map lives in services/execution/reference_resolver.py.
ReferenceKind = Literal["inventory", "credential"]


class StaticAttributeDef(BaseModel):
    """One run-scoped trigger input supplied when a run is started — manually by
    the operator, or per-schedule by a WorkflowSchedule. Resolved values are
    persisted on WorkflowRun.run_inputs and seeded into every device's
    attribute_bags under the reserved "run_input" bag — see
    services/execution/run_input_validation.py and
    services/workflow_context/run_inputs.py.

    A ``type == "reference"`` attribute does not carry a literal value but a
    reference to another row: ``ref_kind == "inventory"`` stores an inventory
    id (int), ``ref_kind == "credential"`` stores a credential name (str). The
    reference is resolved at dispatch time, scoped to the triggering user — see
    services/execution/reference_resolver.py.
    """

    name: str = Field(..., min_length=1, max_length=100)
    type: StaticAttributeType
    ref_kind: ReferenceKind | None = None
    default: Any | None = None
    required: bool = False

    @model_validator(mode="after")
    def _check_ref_kind(self) -> StaticAttributeDef:
        if self.type == "reference" and self.ref_kind is None:
            raise ValueError("ref_kind is required when type is 'reference'")
        if self.type != "reference" and self.ref_kind is not None:
            raise ValueError("ref_kind is only valid when type is 'reference'")
        return self


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
    notes: str | None = None
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


class WorkflowNotesUpdate(BaseModel):
    notes: str | None = Field(None, max_length=100_000)


class WorkflowNotesResponse(BaseModel):
    notes: str | None
    updated_at: datetime
