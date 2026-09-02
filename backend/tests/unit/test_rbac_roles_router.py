"""TestClient coverage for routers/rbac/roles.py."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import AccessDeniedError
from core.models.users import User
from routers.rbac.roles import _service
from routers.rbac.roles import router as roles_router
from services.auth.rbac_service import RBACService

_DT = datetime(2026, 1, 1, tzinfo=UTC)


def _role(**over) -> SimpleNamespace:
    base = dict(
        id=1, name="editors", description=None, is_system=False,
        created_at=_DT, updated_at=_DT,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _perm(**over) -> SimpleNamespace:
    base = dict(id=5, resource="workflows", action="read", description=None, created_at=_DT)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(roles_router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    svc = MagicMock()
    app.dependency_overrides[_service] = lambda: svc
    with TestClient(app) as client:
        yield client, svc


class TestListAndCreate:
    def test_list_roles(self, ctx):
        client, svc = ctx
        svc.list_roles.return_value = [_role(), _role(id=2, name="viewers")]
        r = client.get("/api/rbac/roles")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_create_conflict(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = True
        assert client.post("/api/rbac/roles", json={"name": "editors"}).status_code == 409

    def test_create_ok(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = False
        svc.create_role.return_value = _role()
        assert client.post("/api/rbac/roles", json={"name": "editors"}).status_code == 201

    def test_create_access_denied_403(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = False
        svc.create_role.side_effect = AccessDeniedError("nope")
        assert client.post("/api/rbac/roles", json={"name": "editors"}).status_code == 403

    def test_create_unexpected_500(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = False
        svc.create_role.side_effect = RuntimeError("boom")
        r = client.post("/api/rbac/roles", json={"name": "editors"})
        assert r.status_code == 500
        assert set(r.json()["detail"]) == {"message", "error_id"}


class TestGetUpdateDelete:
    def test_get_role_404_and_200(self, ctx):
        client, svc = ctx
        svc.get_role.return_value = None
        assert client.get("/api/rbac/roles/1").status_code == 404
        svc.get_role.return_value = _role()
        svc.get_role_permissions.return_value = [_perm()]
        assert client.get("/api/rbac/roles/1").status_code == 200

    def test_update_role_conflict_404_ok(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = True
        assert client.put("/api/rbac/roles/1", json={"name": "dup"}).status_code == 409
        svc.role_name_exists.return_value = False
        svc.update_role.return_value = None
        assert client.put("/api/rbac/roles/1", json={"description": "x"}).status_code == 404
        svc.update_role.return_value = _role(description="x")
        assert client.put("/api/rbac/roles/1", json={"description": "x"}).status_code == 200

    def test_update_role_access_denied_403(self, ctx):
        client, svc = ctx
        svc.role_name_exists.return_value = False
        svc.update_role.side_effect = AccessDeniedError("System roles cannot be renamed")
        r = client.put("/api/rbac/roles/1", json={"name": "root"})
        assert r.status_code == 403

    def test_delete_role_404_system_and_ok(self, ctx):
        client, svc = ctx
        svc.get_role.return_value = None
        assert client.delete("/api/rbac/roles/1").status_code == 404
        svc.get_role.return_value = _role(is_system=True)
        assert client.delete("/api/rbac/roles/1").status_code == 409
        svc.get_role.return_value = _role(is_system=False)
        assert client.delete("/api/rbac/roles/1").status_code == 204


class TestRolePermissions:
    def test_get_role_permissions_404_and_200(self, ctx):
        client, svc = ctx
        svc.get_role.return_value = None
        assert client.get("/api/rbac/roles/1/permissions").status_code == 404
        svc.get_role.return_value = _role()
        svc.get_role_permissions.return_value = [_perm()]
        assert client.get("/api/rbac/roles/1/permissions").status_code == 200

    def test_assign_permission_paths(self, ctx):
        client, svc = ctx
        body = {"role_id": 1, "permission_id": 5, "granted": True}
        svc.get_role.return_value = None
        assert client.post("/api/rbac/roles/1/permissions", json=body).status_code == 404
        svc.get_role.return_value = _role()
        svc.get_permission_by_id.return_value = None
        assert client.post("/api/rbac/roles/1/permissions", json=body).status_code == 404
        svc.get_permission_by_id.return_value = _perm()
        assert client.post("/api/rbac/roles/1/permissions", json=body).status_code == 204
        svc.assign_permission_to_role.side_effect = AccessDeniedError("no")
        assert client.post("/api/rbac/roles/1/permissions", json=body).status_code == 403

    def test_remove_permission_paths(self, ctx):
        client, svc = ctx
        svc.remove_permission_from_role.return_value = True
        assert client.delete("/api/rbac/roles/1/permissions/5").status_code == 204
        svc.remove_permission_from_role.return_value = False
        assert client.delete("/api/rbac/roles/1/permissions/5").status_code == 404
        svc.remove_permission_from_role.side_effect = AccessDeniedError("no")
        assert client.delete("/api/rbac/roles/1/permissions/5").status_code == 403
