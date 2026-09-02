"""S5: token_version revocation, absolute session lifetime, and the bump call
sites (logout, password/username change, deactivation)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import _load_active_user, get_current_user_allow_password_change
from core.config import settings
from core.database import get_db
from core.models.users import User
from routers.auth import router as auth_router
from services.auth.auth_service import AuthenticationError, AuthService


def _user(*, user_id: int = 1, is_active: bool = True, token_version: int = 0) -> User:
    user = User(username="alice", password_hash="hash", is_active=is_active)
    user.id = user_id
    user.token_version = token_version
    return user


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


class CreateAccessTokenClaimsTests(unittest.TestCase):
    def test_token_carries_iat_jti_tv_sid_iat(self) -> None:
        user = _user(token_version=3)
        service = AuthService(MagicMock())
        token, _ = service.create_access_token(user)

        claims = _decode(token)
        self.assertEqual(claims["tv"], 3)
        self.assertIsInstance(claims["sid_iat"], int)
        self.assertIsInstance(claims["iat"], int)
        self.assertIsInstance(claims["jti"], str)

    def test_exp_is_clamped_to_the_session_deadline(self) -> None:
        user = _user()
        service = AuthService(MagicMock())
        # Session started (session_max_age - 5 min) ago: exp must land ~5 min out,
        # well under the full access-token TTL.
        started = datetime.now(UTC) - timedelta(
            hours=settings.session_max_age_hours, minutes=-5
        )
        _token, expires_in = service.create_access_token(user, sid_iat=started)
        self.assertLess(expires_in, settings.access_token_expire_minutes * 60)
        self.assertGreater(expires_in, 0)

    def test_refuses_to_mint_for_an_already_expired_session(self) -> None:
        user = _user()
        service = AuthService(MagicMock())
        started = datetime.now(UTC) - timedelta(hours=settings.session_max_age_hours + 1)
        with self.assertRaises(AuthenticationError):
            service.create_access_token(user, sid_iat=started)


class LoadActiveUserTests(unittest.TestCase):
    def _patch_get_by_id(self, user: User | None) -> None:
        p = patch("core.auth.UserRepository.get_by_id", lambda self, uid: user)
        p.start()
        self.addCleanup(p.stop)

    def test_stale_token_version_is_rejected(self) -> None:
        self._patch_get_by_id(_user(token_version=5))
        with pytest.raises(HTTPException) as exc:
            _load_active_user({"user_id": 1, "tv": 4, "sid_iat": _now_ts()}, MagicMock())
        self.assertEqual(exc.value.status_code, 401)

    def test_matching_token_version_is_accepted(self) -> None:
        self._patch_get_by_id(_user(token_version=5))
        user = _load_active_user(
            {"user_id": 1, "tv": 5, "sid_iat": _now_ts()}, MagicMock()
        )
        self.assertEqual(user.token_version, 5)

    def test_claimless_token_for_active_user_is_not_proactively_rejected(self) -> None:
        # Pre-S5 shape ({sub,user_id,exp}); documents the §0 split — verify is
        # lenient, refresh is strict.
        self._patch_get_by_id(_user())
        user = _load_active_user({"user_id": 1}, MagicMock())
        self.assertEqual(user.id, 1)

    def test_session_older_than_max_age_is_rejected(self) -> None:
        self._patch_get_by_id(_user())
        old = int(
            (
                datetime.now(UTC) - timedelta(hours=settings.session_max_age_hours + 1)
            ).timestamp()
        )
        with pytest.raises(HTTPException) as exc:
            _load_active_user({"user_id": 1, "tv": 0, "sid_iat": old}, MagicMock())
        self.assertEqual(exc.value.status_code, 401)

    def test_deactivated_user_still_rejected(self) -> None:
        self._patch_get_by_id(_user(is_active=False))
        with pytest.raises(HTTPException) as exc:
            _load_active_user({"user_id": 1, "tv": 0, "sid_iat": _now_ts()}, MagicMock())
        self.assertEqual(exc.value.status_code, 401)


class BumpTokenVersionTests(unittest.TestCase):
    def test_bump_increments_by_one(self) -> None:
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = _user(token_version=2)

        service.bump_token_version(1)

        _args, kwargs = service.users.update_user.call_args
        self.assertEqual(kwargs["token_version"], 3)

    def test_bump_is_a_noop_for_unknown_user(self) -> None:
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = None
        service.bump_token_version(999)
        service.users.update_user.assert_not_called()

    def test_change_password_bumps_token_version(self) -> None:
        from services.auth.auth_service import password_hash

        user = _user(token_version=1)
        user.password_hash = password_hash.hash("old-correct-password")
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.update_user.return_value = user

        service.change_password(user, "old-correct-password", "a-brand-new-password")

        _args, kwargs = service.users.update_user.call_args
        self.assertEqual(kwargs["token_version"], 2)


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


class LogoutEndpointTests(unittest.TestCase):
    def test_logout_bumps_token_version(self) -> None:
        auth_service = MagicMock()
        app = FastAPI()
        app.include_router(auth_router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user_allow_password_change] = lambda: _user(
            user_id=7
        )

        with patch("routers.auth.AuthService", lambda _db: auth_service):
            with TestClient(app) as client:
                response = client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 204)
        auth_service.bump_token_version.assert_called_once_with(7)


class UserServiceBumpTests(unittest.TestCase):
    def _service(self, target: User):
        from services.auth.rbac_service import RBACService
        from services.users.user_service import UserService

        svc = UserService(MagicMock())
        svc._repo = MagicMock()
        svc._repo.get_by_id.return_value = target
        # spec so MagicMock allows the assert_* policy methods to be called.
        svc._rbac = MagicMock(spec=RBACService)
        return svc

    def test_password_reset_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, password="a-brand-new-password", actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertEqual(kwargs["token_version"], 5)

    def test_username_change_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, username="renamed", actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertEqual(kwargs["token_version"], 5)

    def test_deactivation_via_update_user_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, is_active=False, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertEqual(kwargs["token_version"], 5)

    def test_reactivation_does_not_bump(self) -> None:
        svc = self._service(_user(token_version=4, is_active=False))
        svc.update_user(1, is_active=True, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertNotIn("token_version", kwargs)

    def test_set_active_false_bumps(self) -> None:
        svc = self._service(_user(token_version=7))
        svc.set_active(1, False, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertEqual(kwargs["token_version"], 8)


if __name__ == "__main__":
    unittest.main()
