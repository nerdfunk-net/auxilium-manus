"""TestClient tests for routers/secret_manager.py: permission gating, 400/404
mapping, and the /test endpoint reporting *failure* on a failed login (SM1)."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import service_factory
from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_secret_manager_connection_service
from routers.secret_manager import router
from services.auth.rbac_service import RBACService
from services.secret_manager.exceptions import SecretManagerAuthError

_ROW = {
    "id": 1, "name": "net", "backend": "openbao", "credential_name": "bao",
    "verify_ssl": True, "is_active": True, "description": None,
    "backend_config": {"addr": "https://vault.internal:8200", "mount": "m"},
    "created_at": "2026-09-16T00:00:00+00:00", "updated_at": "2026-09-16T00:00:00+00:00",
}


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
def connection_service(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    svc.get_connection.return_value = _ROW
    app.dependency_overrides[get_secret_manager_connection_service] = lambda: svc
    return svc


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    reg = MagicMock()
    reg.invalidate = AsyncMock()
    reg.get_or_create = AsyncMock()
    monkeypatch.setattr(service_factory, "get_secret_manager_registry", lambda: reg)
    return reg


def test_list_forbidden_without_permission(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    with TestClient(app) as client:
        response = client.get("/api/secret-manager/connections")
    assert response.status_code == 403
    assert "secret_manager.connections:read" in response.json()["detail"]


def test_create_maps_value_error_to_400(app: FastAPI, connection_service: MagicMock) -> None:
    connection_service.create_connection.side_effect = ValueError("backend_config.addr: bad")
    with TestClient(app) as client:
        response = client.post(
            "/api/secret-manager/connections",
            json={
                "name": "net",
                "backend": "openbao",
                "backend_config": {"addr": "x", "mount": "m"},
            },
        )
    assert response.status_code == 400
    assert "backend_config.addr" in response.json()["detail"]


def test_get_unknown_is_404(app: FastAPI, connection_service: MagicMock) -> None:
    connection_service.get_connection.return_value = None
    with TestClient(app) as client:
        response = client.get("/api/secret-manager/connections/99")
    assert response.status_code == 404


def test_test_endpoint_reports_auth_failure(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    registry.get_or_create.side_effect = SecretManagerAuthError("AppRole login failed")
    with TestClient(app) as client:
        response = client.post("/api/secret-manager/connections/1/test")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "AppRole login failed" in body["message"]
    registry.invalidate.assert_awaited_once_with(1)


def test_test_endpoint_reports_success_only_after_get_or_create(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    with TestClient(app) as client:
        response = client.post("/api/secret-manager/connections/1/test")
    assert response.json() == {"success": True, "message": "Connected successfully"}
    registry.get_or_create.assert_awaited_once()


def test_update_invalidates_registry(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    with TestClient(app) as client:
        response = client.put("/api/secret-manager/connections/1", json={"description": "x"})
    assert response.status_code == 200
    registry.invalidate.assert_awaited_once_with(1)
