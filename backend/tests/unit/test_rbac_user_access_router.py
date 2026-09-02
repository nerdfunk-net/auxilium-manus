"""TestClient coverage for routers/rbac/user_access.py: actor wiring and 403 mapping
(doc/plans/FABE_BACKEND_ISSUES.md §2.5, §2.7)."""

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
from routers.rbac.user_access import _service
from routers.rbac.user_access import router as user_access_router
from services.auth.rbac_service import RBACService
from services.users.user_service import UserService

_DT = datetime(2026, 1, 1, tzinfo=UTC)


def _perm(**over) -> SimpleNamespace:
    base = dict(id=5, resource="workflows", action="read", description=None, created_at=_DT)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(user_access_router, prefix="/api")
    user = User(username="actor", password_hash="h", is_active=True)
    user.id = 7
    app.dependency_overrides[verify_token] = lambda: {"sub": "actor", "user_id": 7}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    svc = MagicMock()
    app.dependency_overrides[_service] = lambda: svc
    monkeypatch.setattr(UserService, "get_user", lambda self, user_id: SimpleNamespace(id=user_id))
    with TestClient(app) as client:
        yield client, svc


class TestAssignRemoveRole:
    def test_assign_role_passes_actor_and_maps_403(self, ctx):
        client, svc = ctx
        svc.get_role.return_value = SimpleNamespace(id=2)
        r = client.post("/api/rbac/users/1/roles", json={"user_id": 1, "role_id": 2})
        assert r.status_code == 204
        svc.assign_role_to_user.assert_called_once_with(1, 2, actor_user_id=7)

        svc.assign_role_to_user.side_effect = AccessDeniedError("nope")
        r = client.post("/api/rbac/users/1/roles", json={"user_id": 1, "role_id": 2})
        assert r.status_code == 403

    def test_remove_role_passes_actor_and_maps_403(self, ctx):
        client, svc = ctx
        svc.remove_role_from_user.return_value = True
        r = client.delete("/api/rbac/users/1/roles/2")
        assert r.status_code == 204
        svc.remove_role_from_user.assert_called_once_with(1, 2, actor_user_id=7)

        svc.remove_role_from_user.side_effect = AccessDeniedError("nope")
        r = client.delete("/api/rbac/users/1/roles/2")
        assert r.status_code == 403

    def test_remove_role_404_when_not_found(self, ctx):
        client, svc = ctx
        svc.remove_role_from_user.return_value = False
        r = client.delete("/api/rbac/users/1/roles/2")
        assert r.status_code == 404


class TestPermissionOverrides:
    def test_set_override_passes_actor_and_maps_403(self, ctx):
        client, svc = ctx
        svc.get_permission_by_id.return_value = _perm()
        body = {"user_id": 1, "permission_id": 5, "granted": True}
        r = client.post("/api/rbac/users/1/permissions", json=body)
        assert r.status_code == 204
        svc.assign_permission_to_user.assert_called_once_with(1, 5, True, actor_user_id=7)

        svc.assign_permission_to_user.side_effect = AccessDeniedError("nope")
        r = client.post("/api/rbac/users/1/permissions", json=body)
        assert r.status_code == 403

    def test_remove_override_passes_actor_and_maps_403(self, ctx):
        client, svc = ctx
        svc.remove_permission_from_user.return_value = True
        r = client.delete("/api/rbac/users/1/permissions/5")
        assert r.status_code == 204
        svc.remove_permission_from_user.assert_called_once_with(1, 5, actor_user_id=7)

        svc.remove_permission_from_user.side_effect = AccessDeniedError("nope")
        r = client.delete("/api/rbac/users/1/permissions/5")
        assert r.status_code == 403
