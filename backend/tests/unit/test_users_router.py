"""TestClient coverage for routers/users.py: password policy, actor wiring, and
403/400 mapping (doc/plans/FABE_BACKEND_ISSUES.md §2.5, §2.7, §4.8)."""

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
from routers.users import _rbac_service, _user_service
from routers.users import router as users_router
from services.auth.password_policy import PasswordPolicyError
from services.auth.rbac_service import RBACService

_DT = datetime(2026, 1, 1, tzinfo=UTC)


def _user(**over) -> SimpleNamespace:
    base = dict(id=2, username="bob", is_active=True, created_at=_DT, updated_at=_DT)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    monkeypatch.setattr(RBACService, "get_user_roles", lambda self, user_id: [])
    app = FastAPI()
    app.include_router(users_router, prefix="/api")
    actor = User(username="actor", password_hash="h", is_active=True)
    actor.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "actor", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: MagicMock()
    svc = MagicMock()
    app.dependency_overrides[_user_service] = lambda: svc
    app.dependency_overrides[_rbac_service] = lambda: RBACService(MagicMock())
    with TestClient(app) as client:
        yield client, svc


class TestCreateUser:
    def test_create_rejects_short_password_422(self, ctx) -> None:
        client, _svc = ctx
        r = client.post("/api/users", json={"username": "new", "password": "short1"})
        assert r.status_code == 422

    def test_create_maps_password_policy_error_400(self, ctx) -> None:
        client, svc = ctx
        svc.create_user.side_effect = PasswordPolicyError("This password is too common")
        r = client.post("/api/users", json={"username": "new", "password": "x" * 12})
        assert r.status_code == 400

    def test_create_ok(self, ctx) -> None:
        client, svc = ctx
        svc.create_user.return_value = _user()
        r = client.post("/api/users", json={"username": "bob", "password": "x" * 12})
        assert r.status_code == 201


class TestUpdateDeleteUser:
    def test_update_passes_actor_and_maps_403(self, ctx) -> None:
        client, svc = ctx
        svc.update_user.return_value = _user()
        r = client.put("/api/users/2", json={"username": "renamed"})
        assert r.status_code == 200
        _args, kwargs = svc.update_user.call_args
        assert kwargs["actor_user_id"] == 1

        svc.update_user.side_effect = AccessDeniedError("nope")
        r = client.put("/api/users/2", json={"username": "renamed"})
        assert r.status_code == 403

    def test_update_maps_password_policy_error_400(self, ctx) -> None:
        client, svc = ctx
        svc.update_user.side_effect = PasswordPolicyError("Password must not equal the username")
        r = client.put("/api/users/2", json={"password": "x" * 12})
        assert r.status_code == 400

    def test_self_delete_403(self, ctx) -> None:
        client, svc = ctx
        svc.delete_user.side_effect = AccessDeniedError(
            "You cannot delete or deactivate your own account"
        )
        r = client.delete("/api/users/1")
        assert r.status_code == 403

    def test_delete_last_admin_403(self, ctx) -> None:
        client, svc = ctx
        svc.delete_user.side_effect = AccessDeniedError("The last administrator cannot be removed")
        r = client.delete("/api/users/2")
        assert r.status_code == 403

    def test_delete_ok(self, ctx) -> None:
        client, svc = ctx
        svc.delete_user.return_value = True
        r = client.delete("/api/users/2")
        assert r.status_code == 204
        _args, kwargs = svc.delete_user.call_args
        assert kwargs["actor_user_id"] == 1


class TestSetActive:
    def test_set_active_passes_actor_and_maps_403(self, ctx) -> None:
        client, svc = ctx
        svc.set_active.return_value = _user(is_active=False)
        r = client.patch("/api/users/2/activate", params={"is_active": False})
        assert r.status_code == 200
        _args, kwargs = svc.set_active.call_args
        assert kwargs["actor_user_id"] == 1

        svc.set_active.side_effect = AccessDeniedError("nope")
        r = client.patch("/api/users/2/activate", params={"is_active": False})
        assert r.status_code == 403
