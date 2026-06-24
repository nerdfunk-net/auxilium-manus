"""Derive persisted workflow step status from StepOutcome list."""

from __future__ import annotations

from models.workflow_context import StepOutcome, WorkflowContext


def derive_step_result_status(
    *,
    outcomes: list[StepOutcome],
    input_context: WorkflowContext,
) -> str:
    """Map executor outcomes to pending|running|success|partial|failed|skipped.

    Per-device failures are represented as data on outcomes, not exceptions.
    """
    del input_context  # reserved for future per-device gating checks

    success_outcome = next((outcome for outcome in outcomes if outcome.name == "success"), None)
    failure_outcome = next((outcome for outcome in outcomes if outcome.name == "failure"), None)

    success_count = (
        len(success_outcome.context.devices) if success_outcome is not None else 0
    )
    failure_count = (
        len(failure_outcome.context.devices) if failure_outcome is not None else 0
    )

    if failure_count > 0 and success_count > 0:
        return "partial"
    if failure_count > 0 and success_count == 0:
        return "failed"
    return "success"
