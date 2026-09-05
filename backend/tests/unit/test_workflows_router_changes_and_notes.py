"""FastAPI TestClient tests for GET /workflows/{id}/changes and
PATCH /workflows/{id}/notes — permission wiring and service delegation,
modeled on tests/unit/test_credentials_router.py."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.workflows import _service
from routers.workflows import router as workflows_router
from services.auth.rbac_service import RBACService


def _make_user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: _make_user(1)
    app.dependency_overrides[get_db] = _override_db
    return app


def test_get_workflow_changes_delegates_to_service(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.get_workflow_changes.return_value = {"changes": []}
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.get("/api/workflows/1/changes")

    assert response.status_code == 200
    assert response.json() == {"changes": []}
    mock_service.get_workflow_changes.assert_called_once_with(workflow_id=1, user_id=1)


def test_update_workflow_notes_passes_body_and_acting_user(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.update_notes.return_value = {
        "notes": "Runs the nightly backup.",
        "updated_at": "2026-09-05T00:00:00Z",
    }
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.patch(
            "/api/workflows/1/notes", json={"notes": "Runs the nightly backup."}
        )

    assert response.status_code == 200
    mock_service.update_notes.assert_called_once_with(
        workflow_id=1, user_id=1, notes="Runs the nightly backup."
    )


def test_update_workflow_notes_accepts_null_to_clear(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.update_notes.return_value = {"notes": None, "updated_at": "2026-09-05T00:00:00Z"}
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.patch("/api/workflows/1/notes", json={"notes": None})

    assert response.status_code == 200
    mock_service.update_notes.assert_called_once_with(workflow_id=1, user_id=1, notes=None)
