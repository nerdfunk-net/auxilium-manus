"""FastAPI TestClient tests for auth/permission gating on ISE routers."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_ise_source_config_service
from routers.sources.ise import ise_source_crud_router, ise_source_ops_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ise_source_crud_router, prefix="/api")
    app.include_router(ise_source_ops_router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


def test_list_sources_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/sources/ise")
    assert response.status_code == 401


def test_list_sources_forbidden_without_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/sources/ise")

    assert response.status_code == 403
    assert "sources.ise:read" in response.json()["detail"]


def test_list_sources_allowed_with_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    mock_service = MagicMock()
    mock_service.list_sources.return_value = []
    app.dependency_overrides[get_ise_source_config_service] = lambda: mock_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.get("/api/sources/ise")

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
            "/api/sources/ise",
            json={
                "source_id": "lab",
                "url": "https://10.10.20.77",
                "username": "admin",
                "password": "C1sco12345!",
            },
        )

    assert response.status_code == 403
    assert "sources.ise:write" in response.json()["detail"]


def test_list_devices_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/sources/ise/lab/devices")
    assert response.status_code == 401


def test_delete_device_requires_delete_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def has_permission(self, user_id, resource, action):
        return action == "read"

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.delete("/api/sources/ise/lab/devices/abc")

    assert response.status_code == 403
    assert "sources.ise:delete" in response.json()["detail"]


def test_create_location_group_requires_write_permission(
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
            "/api/sources/ise/lab/location-groups",
            json={"name": "Building1", "parent_group": "All Locations"},
        )

    assert response.status_code == 403
    assert "sources.ise:write" in response.json()["detail"]


def test_create_root_device_group_requires_write_permission(
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
            "/api/sources/ise/lab/network-device-groups/roots",
            json={"name": "new-root"},
        )

    assert response.status_code == 403
    assert "sources.ise:write" in response.json()["detail"]


def test_delete_device_group_requires_delete_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def has_permission(self, user_id, resource, action):
        return action == "read"

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        response = client.delete("/api/sources/ise/lab/network-device-groups/abc")

    assert response.status_code == 403
    assert "sources.ise:delete" in response.json()["detail"]
