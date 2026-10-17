"""S2-04: a schedule is re-validated against its creator every time it fires."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.schedules import WorkflowSchedule
from core.models.users import User
from core.models.workflows import Workflow
from hatchet.workflows import scheduled_trigger
from hatchet.workflows.scheduled_trigger import ScheduledTriggerInput
from services.auth.rbac_service import RBACService


@pytest.fixture
def db_factory():
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Workflow.__table__,
            WorkflowSchedule.__table__,
            WorkflowRun.__table__,
            WorkflowStepResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def _fire(factory, schedule_id: int, workflow_id: int):
    fn = getattr(scheduled_trigger.dispatch, "_fn", None) or scheduled_trigger.dispatch.fn
    with patch("core.database.SessionLocal", factory):
        return asyncio.run(
            fn(ScheduledTriggerInput(schedule_id=schedule_id, workflow_id=workflow_id), MagicMock())
        )


def _seed(factory, *, active=True, visibility="public", wf_creator=None):
    with factory() as db:
        owner = User(username="owner", password_hash="h", is_active=active)
        other = User(username="other", password_hash="h", is_active=True)
        db.add_all([owner, other])
        db.commit()
        wf = Workflow(
            name="w",
            creator_id=other.id if wf_creator is None else wf_creator,
            visibility=visibility,
            canvas_nodes=[],
            canvas_edges=[],
        )
        db.add(wf)
        db.commit()
        sch = WorkflowSchedule(
            uuid="s1",
            workflow_id=wf.id,
            created_by_id=owner.id,
            schedule_type="cron",
            cron_expression="0 * * * *",
            enabled=True,
            run_inputs={},
        )
        db.add(sch)
        db.commit()
        return sch.id, wf.id, owner.id


def _enabled(factory, schedule_id: int) -> bool:
    with factory() as db:
        return db.get(WorkflowSchedule, schedule_id).enabled


def test_trigger_skips_disabled_schedule(db_factory, monkeypatch) -> None:
    # A row stored disabled (a schedule whose Hatchet registration failed) can never fire.
    monkeypatch.setattr(RBACService, "has_permission", lambda *a, **k: True)
    sid, wid, _ = _seed(db_factory)
    with db_factory() as db:
        db.get(WorkflowSchedule, sid).enabled = False
        db.commit()
    assert _fire(db_factory, sid, wid) == {"skipped": True}


def test_fire_skips_and_disables_for_inactive_creator(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda *a, **k: True)
    sid, wid, _ = _seed(db_factory, active=False)
    result = _fire(db_factory, sid, wid)
    assert result == {"skipped": True, "reason": "creator_not_authorised"}
    assert _enabled(db_factory, sid) is False


def test_fire_skips_for_creator_who_lost_workflows_execute(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda *a, **k: False)
    sid, wid, _ = _seed(db_factory)
    assert _fire(db_factory, sid, wid)["reason"] == "creator_not_authorised"
    assert _enabled(db_factory, sid) is False


def test_fire_skips_when_workflow_became_private_and_creator_is_not_owner(
    db_factory, monkeypatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda *a, **k: True)
    sid, wid, _ = _seed(db_factory, visibility="private")
    assert _fire(db_factory, sid, wid)["reason"] == "creator_not_authorised"
    assert _enabled(db_factory, sid) is False


def test_dispatch_failure_marks_run_failed(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda *a, **k: True)
    sid, wid, _ = _seed(db_factory)
    boom = MagicMock()
    boom.run_no_wait.side_effect = RuntimeError("hatchet down password=hunter2")
    with patch("hatchet.workflows.dispatch.resolve_dispatch_workflow", return_value=boom):
        result = _fire(db_factory, sid, wid)
    assert result["status"] == "failed"
    with db_factory() as db:
        run = db.get(WorkflowRun, result["run_id"])
        assert run.status == "failed"
        assert run.error_id
        assert "hunter2" not in (run.error_message or "")
