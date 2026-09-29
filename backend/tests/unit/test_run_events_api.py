"""RunService.list_events + GET /runs/{id}/events."""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import AccessDeniedError, NotFoundError
from core.models.runs import WorkflowRun, WorkflowRunEvent
from core.models.users import User
from core.models.workflows import Workflow
from models.runs import WorkflowRunEventListResponse
from repositories.run_event_repository import RunEventRepository
from routers.workflow_runs import router as workflow_runs_router
from services.auth.rbac_service import RBACService
from services.execution.run_service import RunService

OWNER_ID = 1
OTHER_USER_ID = 2


class RunServiceListEventsTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowRunEvent.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.workflow = Workflow(name="wf", creator_id=OWNER_ID, visibility="private")
        self.db.add(self.workflow)
        self.db.commit()
        run = WorkflowRun(
            uuid="run-1",
            workflow_id=self.workflow.id,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(run)
        self.db.commit()
        self.run_id = run.id
        events = RunEventRepository(self.db)
        for i in range(3):
            events.add_event(
                run_id=run.id,
                step_node_id="a",
                kind="connect_attempt",
                message=f"e{i}",
                device_name="r1",
            )
        self.service = RunService(self.db)

    def test_returns_events_and_cursor(self) -> None:
        response = self.service.list_events(self.run_id, OWNER_ID)

        self.assertIsInstance(response, WorkflowRunEventListResponse)
        self.assertEqual([e.message for e in response.events], ["e0", "e1", "e2"])
        self.assertEqual(response.next_after_id, response.events[-1].id)
        self.assertEqual(response.events[0].device_name, "r1")

    def test_after_id_pages_forward_and_cursor_holds_when_no_new_events(self) -> None:
        first = self.service.list_events(self.run_id, OWNER_ID, limit=2)
        second = self.service.list_events(self.run_id, OWNER_ID, after_id=first.next_after_id)
        empty = self.service.list_events(self.run_id, OWNER_ID, after_id=second.next_after_id)

        self.assertEqual([e.message for e in first.events], ["e0", "e1"])
        self.assertEqual([e.message for e in second.events], ["e2"])
        self.assertEqual(empty.events, [])
        self.assertEqual(empty.next_after_id, second.next_after_id)

    def test_unknown_run_is_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.list_events(9999, OWNER_ID)

    def test_private_workflow_denies_other_users(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.list_events(self.run_id, OTHER_USER_ID)


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(workflow_runs_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


def test_events_endpoint_requires_auth() -> None:
    bare = FastAPI()
    bare.include_router(workflow_runs_router, prefix="/api")
    with TestClient(bare) as client:
        assert client.get("/api/runs/1/events").status_code == 401


def test_events_endpoint_forbidden_without_read_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)

    with TestClient(app) as client:
        response = client.get("/api/runs/1/events")

    assert response.status_code == 403
    assert "workflow_runs:read" in response.json()["detail"]


def test_events_endpoint_passes_cursor_and_limit_to_the_service(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    service = MagicMock()
    service.list_events.return_value = WorkflowRunEventListResponse(events=[], next_after_id=42)
    monkeypatch.setattr("routers.workflow_runs.RunService", lambda db, *a: service)

    with TestClient(app) as client:
        response = client.get("/api/runs/5/events?after_id=42&limit=50")

    assert response.status_code == 200
    assert response.json() == {"events": [], "next_after_id": 42}
    service.list_events.assert_called_once_with(run_id=5, user_id=1, after_id=42, limit=50)


@pytest.mark.parametrize("query", ["after_id=-1", "limit=0", "limit=100000"])
def test_events_endpoint_rejects_out_of_range_query(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    with TestClient(app) as client:
        response = client.get(f"/api/runs/1/events?{query}")

    assert response.status_code == 422


if __name__ == "__main__":
    unittest.main()
