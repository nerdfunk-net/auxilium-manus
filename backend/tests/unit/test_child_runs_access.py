"""``services/execution/child_runs.py``: the database seams of ``start-workflow`` (W10-12).

Each call opens a short session of its own (the run's session is shared with concurrent
branches), so the step imports no repository and no session factory.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.execution import child_runs


def _session_factory(db: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__enter__.return_value = db
    factory.return_value.__exit__.return_value = False
    return factory


@pytest.fixture
def db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def parent() -> MagicMock:
    return MagicMock(status="running")


def _patched(db: MagicMock, parent_run: MagicMock | None, service: MagicMock | None = None):
    repo = MagicMock()
    repo.return_value.get_run.return_value = parent_run
    return (
        patch("core.database.SessionLocal", _session_factory(db)),
        patch("repositories.run_repository.RunRepository", repo),
        patch("services.execution.run_service.RunService", service or MagicMock()),
        repo,
    )


def test_load_child_target_returns_the_workflow_fields_of_the_child(db, parent) -> None:
    service = MagicMock()
    workflow = MagicMock(canvas_nodes=[{"id": "a"}], static_attributes=[{"k": 1}])
    workflow.name = "child"
    service.return_value.require_child_target.return_value = workflow
    a, b, c, repo = _patched(db, parent, service)
    with a, b, c:
        target = child_runs.load_child_target(7, 42)

    repo.return_value.get_run.assert_called_once_with(7)
    service.assert_called_once_with(db)
    service.return_value.require_child_target.assert_called_once_with(parent, 42)
    assert target == child_runs.ChildTarget(
        name="child", canvas_nodes=[{"id": "a"}], static_attributes=[{"k": 1}]
    )


def test_a_missing_calling_run_is_reported_by_every_call_that_needs_it(db) -> None:
    a, b, c, _ = _patched(db, None)
    with a, b, c:
        with pytest.raises(child_runs.CallingRunMissingError, match="calling run no longer exists"):
            child_runs.load_child_target(7, 42)
        with pytest.raises(child_runs.CallingRunMissingError):
            child_runs.start_child(7, 42, {"x": 1})


def test_start_child_forwards_the_inputs_and_returns_the_new_run_id(db, parent) -> None:
    service = MagicMock()
    service.return_value.start_child_run.return_value = MagicMock(id=99)
    a, b, c, _ = _patched(db, parent, service)
    with a, b, c:
        assert child_runs.start_child(7, 42, {"devices": "a,1.1.1.1"}) == 99

    service.return_value.start_child_run.assert_called_once_with(
        parent, 42, run_inputs={"devices": "a,1.1.1.1"}
    )


def test_child_snapshot_asks_the_service_for_that_run(db) -> None:
    service = MagicMock()
    service.return_value.child_run_snapshot.return_value = "snap"
    a, b, c, _ = _patched(db, None, service)
    with a, b, c:
        assert child_runs.child_snapshot(5) == "snap"

    service.return_value.child_run_snapshot.assert_called_once_with(5)


@pytest.mark.parametrize(("status", "expected"), [("cancelled", True), ("running", False)])
def test_parent_cancelled_reads_fresh_data(db, status, expected) -> None:
    parent_run = MagicMock(status=status)
    a, b, c, _ = _patched(db, parent_run)
    with a, b, c:
        assert child_runs.parent_cancelled(7) is expected

    db.refresh.assert_called_once_with(parent_run)


def test_a_vanished_parent_counts_as_cancelled(db) -> None:
    a, b, c, _ = _patched(db, None)
    with a, b, c:
        assert child_runs.parent_cancelled(7) is True
    db.refresh.assert_not_called()
