from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

RunStatus = Literal["pending", "running", "paused", "success", "failed", "cancelled"]
# configuration: the step/run raised a ValueError — almost always a fixable setup
#   problem (missing/invalid config, bad reference) and the message is safe to show.
# execution: the step/run raised a RuntimeError — a step-defined "this run failed"
#   condition (e.g. device unreachable); message is safe to show but not user-fixable
#   by editing the workflow.
# internal: an unexpected exception type — message is withheld to avoid leaking
#   internals; only the error_id (correlatable with worker logs) is shown.
ErrorCategory = Literal["configuration", "execution", "internal"]
RunListStatusFilter = Literal[
    "pending", "running", "paused", "success", "failed", "cancelled", "skipped"
]
StepStatus = Literal["pending", "running", "success", "partial", "failed", "skipped"]
TriggerType = Literal["manual", "scheduled", "webhook"]
RunMode = Literal["normal", "debug"]

RUN_LIST_STATUS_FILTERS: frozenset[str] = frozenset(
    ["pending", "running", "paused", "success", "failed", "cancelled", "skipped"]
)
RUN_STATUS_FILTERS: frozenset[str] = frozenset(
    ["pending", "running", "paused", "success", "failed", "cancelled"]
)
# Safe to purge via retention — never delete pending/running/paused runs.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(["success", "failed", "cancelled"])


class WorkflowRunCreate(BaseModel):
    device_ids: list[str] = []
    trigger_type: TriggerType = "manual"
    run_mode: RunMode = "normal"
    # Values supplied for the workflow's declared static_attributes.
    # Validated/defaulted server-side — see run_input_validation.resolve_run_inputs.
    run_inputs: dict[str, Any] = {}


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
    error_category: ErrorCategory | None = None
    error_id: str | None = None
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
    run_mode: str
    current_node_id: str | None
    debug_message: str | None
    approval_state: dict[str, Any] | None = None
    device_ids: list[str] | None
    run_inputs: dict[str, Any] | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunResponse(WorkflowRunSummary):
    hatchet_run_id: str | None
    error_message: str | None
    error_category: ErrorCategory | None = None
    error_id: str | None = None
    step_results: list[WorkflowStepResultResponse] = []


class WorkflowRunListResponse(BaseModel):
    runs: list[WorkflowRunSummary]
    total: int
