from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ValidationFinding(BaseModel):
    node_id: str | None
    tier: int
    severity: Literal["error", "warning"]
    code: str
    message: str


class WorkflowValidationResult(BaseModel):
    findings: list[ValidationFinding]
    has_errors: bool
