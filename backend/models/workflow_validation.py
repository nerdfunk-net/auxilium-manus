from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class WorkflowValidateRequest(BaseModel):
    """Optional body for POST /workflows/{id}/validate. When `canvas_nodes` is
    given, it is validated as-is instead of the workflow's last-saved state —
    lets the canvas Validate button check unsaved edits."""

    canvas_nodes: list[dict[str, Any]] | None = None


class ValidationFinding(BaseModel):
    node_id: str | None
    tier: int
    severity: Literal["error", "warning"]
    code: str
    message: str


class WorkflowValidationResult(BaseModel):
    findings: list[ValidationFinding]
    has_errors: bool
