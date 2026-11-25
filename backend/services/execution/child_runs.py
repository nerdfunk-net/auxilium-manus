"""Database access of the ``start-workflow`` step (W10-12).

Every call opens a short session of its own and is meant to run in a thread: the run's session is
shared with concurrent branches of the workflow, so a step must not use it for these reads and
writes. The imports are local on purpose: ``services.execution.run_service`` reaches the step
registry, and the step imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
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


def validate_child_inputs(
    parent_run_id: int, workflow_id: int, inputs_per_run: list[dict[str, Any]]
) -> None:
    """Check the run inputs of every run the step is about to start, starting none.

    The same resolution ``RunService.start_child_run`` applies: a ``ValidationFailedError`` names
    the input that is wrong. One session for all of them.
    """
    from core.database import SessionLocal
    from core.domain_exceptions import ValidationFailedError
    from repositories.run_repository import RunRepository
    from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise CallingRunMissingError
        workflow = RunService(db).require_child_target(parent, workflow_id)
        for run_inputs in inputs_per_run:
            try:
                resolve_run_inputs(workflow.static_attributes, run_inputs)
            except RunInputValidationError as exc:
                raise ValidationFailedError(str(exc)) from exc


def start_child(parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any]) -> int:
    """Start ``workflow_id`` as a child of ``parent_run_id``; the id of the new run.

    Raises ``EngineUnavailableError`` when the run could not be dispatched (the service answers
    503 for that), so the step does not need to know about HTTP.
    """
    from fastapi import HTTPException

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.dispatch_breaker import EngineUnavailableError
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise CallingRunMissingError
        try:
            return RunService(db).start_child_run(parent, workflow_id, run_inputs=run_inputs).id
        except HTTPException as exc:
            if exc.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
                message = "the workflow execution engine is unavailable"
                raise EngineUnavailableError(message) from exc
            raise


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
