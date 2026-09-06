"""Return-value types for the step runner, kept in their own module so the
Hatchet layer (``hatchet/workflows/workflow_run/``) can import ``FanOutSignal``
and ``classify_step_exception`` without pulling in the whole StepRunner class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.workflow_context import WorkflowContext


@dataclass
class FanOutSignal:
    """Returned by execute_all when an inventory step requests fan-out."""

    inventory_node_id: str
    fan_out_config: dict[str, Any]
    inventory_outcome: WorkflowContext  # context with all devices + _fan_out metadata
    step_outcomes: dict[str, dict[str, WorkflowContext]] = field(default_factory=dict)
    # node_id of the fan-in (join) step downstream of the inventory step, if any.
    # When set, children stop before it and the parent runs it (and everything
    # downstream of it) once on the merged context. When None, children run the
    # whole downstream subgraph (legacy behaviour).
    join_node_id: str | None = None


def classify_step_exception(exc: Exception) -> tuple[str, str]:
    """Map a raised exception to (error_category, user-facing message).

    Steps follow the convention documented in doc/WORKFLOW-STEPS.md: raise
    ``ValueError`` for configuration problems (missing/invalid settings,
    unresolved references) and ``RuntimeError`` for expected-but-failed
    execution conditions (e.g. a device unreachable). Both are authored by
    step code with human-readable messages, so it's safe to show them
    directly. Anything else is an unanticipated bug — its message may
    contain internals (paths, library-specific text) so it's withheld;
    only the error_id (correlatable with the full traceback in worker
    logs) is shown.
    """
    if isinstance(exc, ValueError):
        return "configuration", str(exc) or "This step's configuration is invalid."
    if isinstance(exc, RuntimeError):
        return "execution", str(exc) or "This step failed to complete."
    return "internal", "An unexpected internal error occurred while running this step."
