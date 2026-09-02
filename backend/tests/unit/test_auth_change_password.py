"""Tests for AuthService.change_password and POST /auth/change-password
(doc/plans/FABE_BACKEND_ISSUES.md §4.6, §4.8)."""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_login_rate_limiter
from routers.auth import router as auth_router
from services.auth.auth_service import AuthenticationError, AuthService, password_hash
from services.auth.password_policy import PasswordPolicyError
from services.auth.rbac_service import RBACService


def _user(*, must_change_password: bool = True) -> User:
    user = User(
        username="alice",
        password_hash=password_hash.hash("old-correct-password"),
        is_active=True,
        must_change_password=must_change_password,
    )
    user.id = 1
    return user


class TestAuthServiceChangePassword(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AuthService(MagicMock())
        self.service.users = MagicMock()

    def test_wrong_current_password_raises(self) -> None:
        user = _user()
        self.service.users.get_by_id.return_value = user
        with self.assertRaises(AuthenticationError):
            self.service.change_password(user, "not-the-current-password", "x" * 20)

    def test_policy_violation_raises(self) -> None:
        user = _user()
        with self.assertRaises(PasswordPolicyError):
            self.service.change_password(user, "old-correct-password", "short")

    def test_success_clears_must_change_password(self) -> None:
        user = _user()
        updated = _user(must_change_password=False)
        self.service.users.update_user.return_value = updated

        result = self.service.change_password(user, "old-correct-password", "x" * 20)

        self.assertFalse(result.must_change_password)
        _args, kwargs = self.service.users.update_user.call_args
        self.assertEqual(kwargs["must_change_password"], False)
        self.assertTrue(password_hash.verify("x" * 20, kwargs["password_hash"]))

    def test_new_password_actually_changes_credential(self) -> None:
        # End-to-end against a real (non-mocked) hash: the old password no
        # longer verifies against the hash produced by change_password.
        user = _user()
        captured: dict[str, str] = {}

        def _update_user(_user_id: int, **kwargs: object) -> User:
            captured.update(kwargs)  # type: ignore[arg-type]
            return _user(must_change_password=False)

        self.service.users.update_user.side_effect = _update_user

        self.service.change_password(user, "old-correct-password", "x" * 20)

        self.assertFalse(password_hash.verify("old-correct-password", captured["password_hash"]))
        self.assertTrue(password_hash.verify("x" * 20, captured["password_hash"]))


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "get_user_roles", lambda self, _uid: [])
    monkeypatch.setattr(RBACService, "get_user_permission_strings", lambda self, _uid: [])
    rate_limiter = MagicMock()
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_login_rate_limiter] = lambda: rate_limiter
    with TestClient(app) as client:
        yield client, rate_limiter


class TestChangePasswordEndpoint:
    def test_wrong_current_password_400(self, ctx, monkeypatch) -> None:
        client, _rl = ctx
        import core.auth as core_auth

        client.app.dependency_overrides[core_auth.get_current_user_allow_password_change] = (
            lambda: _user()
        )
        monkeypatch.setattr(
            AuthService,
            "change_password",
            lambda self, user, cur, new: (_ for _ in ()).throw(
                AuthenticationError("Current password is incorrect")
            ),
        )

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "x" * 20},
        )
        assert r.status_code == 400

    def test_policy_violation_400(self, ctx) -> None:
        client, _rl = ctx
        import core.auth as core_auth

        client.app.dependency_overrides[core_auth.get_current_user_allow_password_change] = (
            lambda: _user()
        )

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "old-correct-password", "new_password": "short"},
        )
        assert r.status_code == 422  # Pydantic min_length rejects it before the service runs

    def test_success_returns_updated_user_and_clears_flag(self, ctx, monkeypatch) -> None:
        client, rate_limiter = ctx
        import core.auth as core_auth

        client.app.dependency_overrides[core_auth.get_current_user_allow_password_change] = (
            lambda: _user()
        )
        monkeypatch.setattr(
            AuthService,
            "change_password",
            lambda self, user, cur, new: _user(must_change_password=False),
        )

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "old-correct-password", "new_password": "x" * 20},
        )

        assert r.status_code == 200
        assert r.json()["must_change_password"] is False
        rate_limiter.clear.assert_called_once()

    def test_rate_limited_returns_429(self, ctx) -> None:
        from services.auth.login_rate_limiter import RateLimitExceededError

        client, rate_limiter = ctx
        import core.auth as core_auth

        client.app.dependency_overrides[core_auth.get_current_user_allow_password_change] = (
            lambda: _user()
        )
        rate_limiter.check.side_effect = RateLimitExceededError("change-password:1")

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "old-correct-password", "new_password": "x" * 20},
        )
        assert r.status_code == 429

    def test_me_accessible_while_must_change_password_is_set(self, ctx) -> None:
        # /auth/me must keep working for a user blocked everywhere else, so
        # the frontend can read the flag and render the forced dialog.
        client, _rl = ctx
        import core.auth as core_auth

        client.app.dependency_overrides[core_auth.get_current_user_allow_password_change] = (
            lambda: _user(must_change_password=True)
        )

        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True

    def test_other_endpoints_blocked_while_must_change_password_is_set(self, ctx) -> None:
        # get_current_user (not the _allow_password_change variant) must still
        # block, proving the two dependencies are genuinely distinct here.
        client, _rl = ctx
        app = FastAPI()
        app.dependency_overrides[verify_token] = lambda: {"sub": "alice", "user_id": 1}
        app.dependency_overrides[get_db] = _override_db

        from fastapi import Depends

        @app.get("/protected")
        def _protected(user: User = Depends(get_current_user)) -> dict:
            return {"id": user.id}

        import core.auth as core_auth

        with TestClient(app) as protected_client:
            with patch.object(
                core_auth.UserRepository,
                "get_by_id",
                return_value=_user(must_change_password=True),
            ):
                r = protected_client.get("/protected")

        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "password_change_required"


if __name__ == "__main__":
    unittest.main()
