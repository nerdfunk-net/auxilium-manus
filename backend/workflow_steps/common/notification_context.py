"""Shared workflow lookup and row writes for the notification and statistics steps."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.database import get_db_session
from core.models.runs import WorkflowRun
from core.models.workflows import Workflow
from repositories.job_statistics_repository import JobStatisticsRepository
from repositories.notification_repository import NotificationRepository
from repositories.workflow_repository import WorkflowRepository
from workflow_steps.common.run_session import require_session


def resolve_run_workflow(run: WorkflowRun, *, step_id: str) -> tuple[Workflow, str | None]:
    """The owning Workflow of a run and its owner's username (read on the run's session).

    Shared by ``notify``, ``notify-on-error`` and ``collect-statistics`` so they raise the same
    errors for the same conditions. ``step_id`` (e.g. ``"notify"``) only prefixes the messages.
    """
    db = require_session(run, step_id)

    result = WorkflowRepository(db).get_by_id(run.workflow_id)
    if result is None:
        raise ValueError(f"{step_id}: workflow {run.workflow_id} not found")
    return result


def write_notifications(*, run_id: int, node_id: str, rows: list[dict[str, Any]]) -> int:
    """Replace this node's notification rows in a session of its own (W9-09); the count written.

    The run's session is never committed here: a commit would flush whatever the runner has
    pending, and a failed write must not leave that session needing a rollback.
    """
    db: Session = get_db_session()
    try:
        written = NotificationRepository(db).replace_for_node(
            run_id=run_id, node_id=node_id, rows=rows
        )
        return len(written)
    finally:
        db.close()


def write_statistics(*, run_id: int, node_id: str, rows: list[dict[str, Any]]) -> int:
    """Replace this node's statistics rows in a session of its own; the count written."""
    db: Session = get_db_session()
    try:
        written = JobStatisticsRepository(db).replace_for_node(
            run_id=run_id, node_id=node_id, rows=rows
        )
        return len(written)
    finally:
        db.close()
