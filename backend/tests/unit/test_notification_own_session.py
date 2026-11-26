"""W9-09: the notification and statistics rows are written in a session of their own.

``notify`` (Notify Local), ``notify-on-error`` (Notify On Error) and ``collect-statistics``
(Collect Statistics) used to commit the runner's session (``object_session(run)``): the commit
flushed whatever the runner had pending, and a failed write could leave that session to be rolled
back by the runner. The write now opens, commits and closes its own session; the run session is
only read (the workflow lookup).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session

from core.models.job_statistics import JobStatistic
from core.models.notifications import Notification
from models.workflow_context import DeviceContext, DeviceError, WorkflowContext
from repositories.job_statistics_repository import JobStatisticsRepository
from workflow_steps.collect_statistics import executor as statistics_executor
from workflow_steps.notify import executor as notify_executor
from workflow_steps.notify_on_error import executor as on_error_executor

pytestmark = pytest.mark.asyncio

_CONTEXT_MODULE = "workflow_steps.common.notification_context"


class _ClosingSession(Session):
    closed_calls = 0

    def close(self) -> None:
        type(self).closed_calls += 1
        super().close()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    cast(Table, Notification.__table__).create(engine)
    cast(Table, JobStatistic.__table__).create(engine)
    _ClosingSession.closed_calls = 0
    return engine


@pytest.fixture
def run_session() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def patched(engine, run_session) -> Iterator[None]:
    workflow = MagicMock()
    workflow.id = 5
    workflow.name = "wf"
    workflow_repo = MagicMock()
    workflow_repo.get_by_id.return_value = (workflow, "alice")
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=run_session),
        patch(f"{_CONTEXT_MODULE}.WorkflowRepository", return_value=workflow_repo),
        patch(
            f"{_CONTEXT_MODULE}.get_db_session",
            side_effect=lambda: _ClosingSession(engine),
            create=True,
        ),
    ):
        yield


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    run.workflow_id = 5
    return run


def _context(*, with_error: bool = False) -> WorkflowContext:
    device = DeviceContext(id="d1", name="r1", hostname="r1")
    if with_error:
        device.errors.append(DeviceError(node_id="n", step_id="s", code="c", message="boom"))
    return WorkflowContext(run_id="u", workflow_id="w", devices={"d1": device})


def _assert_run_session_untouched(run_session: MagicMock) -> None:
    run_session.commit.assert_not_called()
    run_session.rollback.assert_not_called()
    run_session.add_all.assert_not_called()
    run_session.execute.assert_not_called()


def _rows(engine, model) -> list:
    with Session(engine) as db:
        return list(db.scalars(select(model)))


@pytest.mark.usefixtures("patched")
async def test_notify_writes_in_its_own_session(engine, run_session) -> None:
    outcomes = await notify_executor.execute(
        config={"message": "hello {device.name}", "severity": "info"},
        context=_context(),
        run=_run(),
        artifact_service=MagicMock(),
        node_id="n1",
        device_sessions=MagicMock(),
    )

    assert [o.name for o in outcomes] == ["success"]
    assert (outcomes[0].summary or "").startswith("notified 1 device(s)")
    assert [(n.node_id, n.device_name, n.message) for n in _rows(engine, Notification)] == [
        ("n1", "r1", "hello r1")
    ]
    _assert_run_session_untouched(run_session)
    assert _ClosingSession.closed_calls == 1


@pytest.mark.usefixtures("patched")
async def test_notify_on_error_writes_in_its_own_session(engine, run_session) -> None:
    outcomes = await on_error_executor.execute(
        config={"message": "failed {device.name}"},
        context=_context(with_error=True),
        run=_run(),
        artifact_service=MagicMock(),
        node_id="n2",
        device_sessions=MagicMock(),
    )

    assert [o.name for o in outcomes] == ["success"]
    assert [(n.node_id, n.device_name) for n in _rows(engine, Notification)] == [("n2", "r1")]
    _assert_run_session_untouched(run_session)
    assert _ClosingSession.closed_calls == 1


@pytest.mark.usefixtures("patched")
async def test_collect_statistics_writes_in_its_own_session(engine, run_session) -> None:
    outcomes = await statistics_executor.execute(
        config={"result": "success"},
        context=_context(),
        run=_run(),
        artifact_service=MagicMock(),
        node_id="n3",
        device_sessions=MagicMock(),
    )

    assert outcomes[0].summary == "recorded 1 device(s) as success"
    assert [(s.node_id, s.device_name, s.result) for s in _rows(engine, JobStatistic)] == [
        ("n3", "r1", "success")
    ]
    _assert_run_session_untouched(run_session)
    assert _ClosingSession.closed_calls == 1


@pytest.mark.usefixtures("patched")
async def test_own_session_is_closed_when_the_write_fails(engine, run_session) -> None:
    with (
        patch.object(_ClosingSession, "commit", side_effect=RuntimeError("db down")),
        pytest.raises(RuntimeError, match="db down"),
    ):
        await notify_executor.execute(
            config={"message": "m", "severity": "info"},
            context=_context(),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )

    assert _rows(engine, Notification) == []
    _assert_run_session_untouched(run_session)
    assert _ClosingSession.closed_calls == 1


async def test_statistics_replace_rolls_back_on_failure() -> None:
    db = MagicMock()
    db.commit.side_effect = RuntimeError("db down")
    row = {
        "run_id": 1,
        "node_id": "n",
        "workflow_id": 5,
        "workflow_name": "wf",
        "device_name": "r1",
        "result": "success",
    }
    with pytest.raises(RuntimeError):
        JobStatisticsRepository(db).replace_for_node(run_id=1, node_id="n", rows=[row])
    db.rollback.assert_called_once()
