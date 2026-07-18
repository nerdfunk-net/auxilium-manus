"""FastAPI TestClient tests for auth and permission gating on routers."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from main import health_check
from models.workflows import WorkflowListResponse
from routers.netmiko import router as netmiko_router
from routers.workflows import router as workflows_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_api_route("/health", health_check, methods=["GET"])
    app.include_router(workflows_router, prefix="/api")
    app.include_router(netmiko_router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


def test_health_ok(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workflows_list_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/workflows")
    assert response.status_code == 401


def test_netmiko_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.post("/api/netmiko/run-commands", json={})
    assert response.status_code == 401


def test_workflows_list_forbidden_without_permission(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/workflows")

    assert response.status_code == 403
    assert "workflows:read" in response.json()["detail"]


def test_workflows_list_allowed_with_permission(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    mock_service = MagicMock()
    mock_service.list_workflows.return_value = WorkflowListResponse(workflows=[], total=0)
    monkeypatch.setattr(
        "routers.workflows.WorkflowService",
        lambda db: mock_service,
    )

    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/workflows")

    assert response.status_code == 200
    mock_service.list_workflows.assert_called_once()
