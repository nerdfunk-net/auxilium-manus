"""DbReleasedWorkflowReader and the session gating of the released-workflow tools."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.users import User
from core.models.workflows import Workflow
from services.ai_assistant import released_workflow_reader as module
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.released_workflow_reader import (
    DbReleasedWorkflowReader,
    ReleasedWorkflowAccessError,
)
from services.ai_assistant.surfaces import build_general_session
from services.auth.rbac_service import RBACService


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Workflow.metadata.create_all(engine, tables=[User.__table__, Workflow.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    session = factory()
    session.add_all(
        [
            Workflow(
                id=1,
                name="released",
                creator_id=1,
                visibility="public",
                ai_released=True,
                ai_description="Compare snapshot",
                ai_result_node_id="cmp",
                static_attributes=[{"name": "f", "type": "string"}],
            ),
            Workflow(id=2, name="plain", creator_id=1, visibility="public", ai_released=False),
            Workflow(id=3, name="mine", creator_id=1, visibility="private", ai_released=True),
        ]
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_lists_only_released_workflows_the_user_may_see(db) -> None:
    other = asyncio.run(DbReleasedWorkflowReader(2).list_released())
    owner = asyncio.run(DbReleasedWorkflowReader(1).list_released())
    assert [w.id for w in other] == [1]
    assert sorted(w.id for w in owner) == [1, 3]
    assert other[0].description == "Compare snapshot" and other[0].result_node_id == "cmp"


@pytest.mark.parametrize("workflow_id", [2, 3, 99])
def test_get_refuses_unreleased_private_or_missing(db, workflow_id: int) -> None:
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(DbReleasedWorkflowReader(2).get_released(workflow_id))


def test_without_execute_permission_nothing_is_available(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    reader = DbReleasedWorkflowReader(2)
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(reader.list_released())
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(reader.get_released(1))
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(reader.start(1, run_inputs={}, device_ids=[]))


class _Runs:
    pass


def _names(**kw) -> set[str]:
    session = build_general_session(
        user_id=1,
        reader=object(),
        store=None,
        sharing=SharingPolicy(),
        may_query_batfish=False,
        **kw,
    )
    return {s.name for s in session.toolbox.specs()}


def test_tools_need_both_the_released_reader_and_the_run_reader() -> None:
    wanted = {
        "list_released_workflows",
        "describe_workflow",
        "propose_workflow_run",
        "get_run_result",
    }
    assert wanted <= _names(released_reader=object(), run_reader=_Runs())
    assert not wanted & _names(released_reader=object())
    assert not wanted & _names(run_reader=_Runs())
