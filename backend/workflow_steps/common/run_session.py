"""The database session a workflow step uses (the only place that asks the run for it)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, object_session

if TYPE_CHECKING:
    from core.models import WorkflowRun


def require_session(run: WorkflowRun, step_id: str) -> Session:
    """The session ``run`` is attached to; a run without one is a bug, never a user error."""
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{step_id}: WorkflowRun has no active DB session")
    return db
