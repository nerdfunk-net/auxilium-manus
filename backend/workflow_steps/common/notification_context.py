"""Shared DB-session/workflow lookup for notification-writing steps."""

from __future__ import annotations

from sqlalchemy.orm import Session, object_session

from core.models.runs import WorkflowRun
from core.models.workflows import Workflow
from repositories.workflow_repository import WorkflowRepository


def resolve_run_workflow(run: WorkflowRun, *, step_id: str) -> tuple[Session, Workflow, str | None]:
    """Resolve the active DB session and owning Workflow for a run.

    Shared by ``notify`` and ``notify-on-error`` so both raise the same
    errors for the same conditions. ``step_id`` (e.g. ``"notify"``) is only
    used to prefix error messages.
    """
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{step_id}: WorkflowRun has no active DB session")

    result = WorkflowRepository(db).get_by_id(run.workflow_id)
    if result is None:
        raise ValueError(f"{step_id}: workflow {run.workflow_id} not found")
    workflow, owner_username = result
    return db, workflow, owner_username
