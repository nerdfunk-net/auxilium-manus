"""FastAPI TestClient tests for auth/permission gating on pyATS source routers."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_pyats_source_config_service
from routers.sources.pyats import pyats_source_crud_router, pyats_source_ops_router
from services.auth.rbac_service import RBACService
from services.pyats.common.exceptions import PyATSAPIError


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(pyats_source_crud_router, prefix="/api")
    app.include_router(pyats_source_ops_router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


def test_list_sources_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/sources/pyats")
    assert response.status_code == 401


def test_list_sources_forbidden_without_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/sources/pyats")

    assert response.status_code == 403
    assert "sources.pyats:read" in response.json()["detail"]


def test_list_sources_allowed_with_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    mock_service = MagicMock()
    mock_service.list_sources.return_value = []
    app.dependency_overrides[get_pyats_source_config_service] = lambda: mock_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/sources/pyats")

    assert response.status_code == 200
    assert response.json() == {"sources": [], "total": 0}


def test_create_source_requires_write_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def has_permission(self, user_id, resource, action):
        return action == "read"

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/pyats",
            json={
                "source_id": "lab",
                "url": "http://pyats-shim:8100",
                "token": "s3cr3t",
            },
        )

    assert response.status_code == 403
    assert "sources.pyats:write" in response.json()["detail"]


def test_delete_source_requires_delete_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def has_permission(self, user_id, resource, action):
        return action == "read"

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.delete("/api/sources/pyats/lab")

    assert response.status_code == 403
    assert "sources.pyats:delete" in response.json()["detail"]


def test_test_connection_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.post("/api/sources/pyats/lab/test-connection")
    assert response.status_code == 401


def test_test_connection_success_reports_versions(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    mock_config_service = MagicMock()
    mock_config_service.resolve_credentials.return_value = MagicMock()
    app.dependency_overrides[get_pyats_source_config_service] = lambda: mock_config_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    import service_factory

    mock_shim = MagicMock()

    async def _check_health(*_a, **_k):
        return {"status": "ok"}

    async def _check_pyats_health(*_a, **_k):
        return {"status": "ok", "pyats_version": "26.7", "genie_version": "26.7"}

    mock_shim.check_health = _check_health
    mock_shim.check_pyats_health = _check_pyats_health
    monkeypatch.setattr(service_factory, "get_pyats_app_service", lambda: mock_shim)

    with TestClient(app) as client:
        response = client.post("/api/sources/pyats/lab/test-connection")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "26.7" in body["message"]


def test_test_connection_reports_shim_unreachable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    mock_config_service = MagicMock()
    mock_config_service.resolve_credentials.return_value = MagicMock()
    app.dependency_overrides[get_pyats_source_config_service] = lambda: mock_config_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    import service_factory

    mock_shim = MagicMock()

    async def _check_health(*_a, **_k):
        raise PyATSAPIError("connection refused")

    mock_shim.check_health = _check_health
    monkeypatch.setattr(service_factory, "get_pyats_app_service", lambda: mock_shim)

    with TestClient(app) as client:
        response = client.post("/api/sources/pyats/lab/test-connection")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "not reachable" in body["message"]
