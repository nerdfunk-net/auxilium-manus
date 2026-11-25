"""Database access of the ``start-workflow`` step (W10-12).

Every call opens a short session of its own and is meant to run in a thread: the run's session is
shared with concurrent branches of the workflow, so a step must not use it for these reads and
writes. The imports are local on purpose: ``services.execution.run_service`` reaches the step
registry, and the step imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CallingRunMissingError(ValueError):
    """The run that executes the step is gone (deleted or purged while it ran)."""

    def __init__(self) -> None:
        super().__init__("the calling run no longer exists")


@dataclass(frozen=True)
class ChildTarget:
    """What the step inspects of the workflow it is about to start."""

    name: str
    canvas_nodes: list[Any]
    static_attributes: list[Any]


def load_child_target(parent_run_id: int, workflow_id: int) -> ChildTarget:
    """The workflow ``parent_run_id`` may start; the domain error says why it may not."""
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise CallingRunMissingError
        workflow = RunService(db).require_child_target(parent, workflow_id)
        return ChildTarget(
            name=workflow.name,
            canvas_nodes=list(workflow.canvas_nodes or []),
            static_attributes=list(workflow.static_attributes or []),
        )


def start_child(parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any]) -> int:
    """Start ``workflow_id`` as a child of ``parent_run_id``; the id of the new run."""
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise CallingRunMissingError
        return RunService(db).start_child_run(parent, workflow_id, run_inputs=run_inputs).id


def child_snapshot(run_id: int) -> Any:
    """The state of a child run (``ChildRunSnapshot``), read fresh."""
    from core.database import SessionLocal
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        return RunService(db).child_run_snapshot(run_id)


def parent_cancelled(run_id: int) -> bool:
    """Whether the calling run was cancelled (a vanished run counts as cancelled)."""
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(run_id)
        if parent is None:
            return True
        db.refresh(parent)
        return parent.status == "cancelled"
