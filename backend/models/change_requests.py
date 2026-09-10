from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ChangeRequestStatus = Literal[
    "staged", "approved", "deploying", "deployed", "failed", "rejected", "expired"
]

# Terminal — a sweep / reconcile never moves these.
TERMINAL_CHANGE_REQUEST_STATUSES: frozenset[str] = frozenset(
    ["deployed", "failed", "rejected", "expired"]
)


class ChangeRequestSummary(BaseModel):
    id: int
    uuid: str
    title: str | None
    status: ChangeRequestStatus
    source_workflow_id: int | None
    source_run_id: int | None
    deploy_workflow_id: int | None
    deploy_run_id: int | None
    branch: str | None
    commit_sha: str | None
    diff_stats: dict[str, Any] | None = None
    approved_via: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChangeRequestResponse(ChangeRequestSummary):
    base_branch: str | None
    git_repository_id: int | None
    device_ids: list[str] = []
    # Nullable in the DB for change requests created before the snapshot existed.
    devices: list[dict[str, Any]] = []
    run_inputs: dict[str, Any] = {}
    diff_artifact_id: str | None = None
    deploy_error: str | None = None
    reject_reason: str | None = None
    approved_by_id: int | None = None
    approved_by_username: str | None = None

    @field_validator("device_ids", "devices", mode="before")
    @classmethod
    def _list_null_to_empty(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("run_inputs", mode="before")
    @classmethod
    def _dict_null_to_empty(cls, value: Any) -> Any:
        return {} if value is None else value


class ChangeRequestListResponse(BaseModel):
    items: list[ChangeRequestSummary]
    total: int


class ChangeRequestApproveRequest(BaseModel):
    # Chosen at approval time when the change request has no pinned
    # deploy_workflow_id. Ignored if a pin already exists.
    deploy_workflow_id: int | None = None


class ChangeRequestRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
