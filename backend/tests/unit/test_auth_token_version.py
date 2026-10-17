"""S5: token_version revocation, absolute session lifetime, and the bump call
sites (logout, password/username change, deactivation)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from _auth_helpers import make_auth_db
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

    def _assert_rejected(self, payload: dict, user: User | None = None) -> None:
        self._patch_get_by_id(user or _user())
        with pytest.raises(HTTPException) as exc:
            _load_active_user(payload, MagicMock())
        self.assertEqual(exc.value.status_code, 401)

    def test_claimless_token_is_rejected(self) -> None:
        # Pre-S5 shape ({sub,user_id,exp}) — T3: both claims are mandatory.
        self._assert_rejected({"user_id": 1})

    def test_token_without_tv_is_rejected(self) -> None:
        self._assert_rejected({"user_id": 1, "sid_iat": _now_ts()})

    def test_token_without_sid_iat_is_rejected(self) -> None:
        self._assert_rejected({"user_id": 1, "tv": 0})

    def test_non_numeric_or_bool_claims_are_rejected(self) -> None:
        for bad in (
            {"tv": "0", "sid_iat": _now_ts()},
            {"tv": False, "sid_iat": _now_ts()},
            {"tv": 0, "sid_iat": "now"},
            {"tv": 0, "sid_iat": None},
            {"tv": 0, "sid_iat": float("nan")},
            {"tv": 0, "sid_iat": 1e20},
        ):
            with self.subTest(claims=bad):
                self._assert_rejected({"user_id": 1, **bad})

    def test_user_without_integer_token_version_is_rejected(self) -> None:
        user = _user()
        user.token_version = MagicMock()  # type: ignore[assignment]
        self._assert_rejected({"user_id": 1, "tv": 0, "sid_iat": _now_ts()}, user)

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

        service.bump_token_version(1)

        _args, kwargs = service.users.update_user.call_args
        # The increment itself happens in SQL (repository), not from a stale row (S1-13).
        self.assertIs(kwargs["bump_token_version"], True)
        self.assertNotIn("token_version", kwargs)

    def test_bump_is_a_noop_for_unknown_user(self) -> None:
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.update_user.return_value = None
        service.bump_token_version(999)  # must not raise

    def test_two_concurrent_bumps_add_two(self) -> None:
        import tempfile

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from repositories.user_repository import UserRepository

        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{tmp}/t.db")
            User.metadata.create_all(engine, tables=[User.__table__])
            factory = sessionmaker(bind=engine)
            setup = factory()
            setup.add(User(username="u", password_hash="h", is_active=True))
            setup.commit()
            uid = setup.query(User).one().id
            start = setup.get(User, uid).token_version
            repo_a, repo_b = UserRepository(factory()), UserRepository(factory())
            # Both load the row first (stale), then bump.
            repo_a.db.get(User, uid)
            repo_b.db.get(User, uid)
            repo_a.update_user(uid, bump_token_version=True)
            repo_b.update_user(uid, bump_token_version=True)
            fresh = factory()
            self.assertEqual(fresh.get(User, uid).token_version, start + 2)
            engine.dispose()

    def test_change_password_bumps_token_version(self) -> None:
        from services.auth.auth_service import password_hash

        user = _user(token_version=1)
        user.password_hash = password_hash.hash("old-correct-password")
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.update_user.return_value = user

        service.change_password(user, "old-correct-password", "a-brand-new-password")

        _args, kwargs = service.users.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], True)

    def test_same_password_is_rejected(self) -> None:
        from core.password_policy import PasswordPolicyError
        from services.auth.auth_service import password_hash

        user = _user(token_version=1)
        user.password_hash = password_hash.hash("InitialPassword-123")
        service = AuthService(MagicMock())
        service.users = MagicMock()
        with self.assertRaises(PasswordPolicyError):
            service.change_password(user, "InitialPassword-123", "InitialPassword-123")
        service.users.update_user.assert_not_called()

    def test_initial_password_is_rejected(self) -> None:
        from core.config import settings
        from core.password_policy import PasswordPolicyError
        from services.auth.auth_service import password_hash

        user = _user(token_version=1)
        user.password_hash = password_hash.hash("some-other-current-pw")
        service = AuthService(MagicMock())
        service.users = MagicMock()
        with patch.object(settings, "initial_password", "Bootstrap-Pass-1234"):
            with self.assertRaises(PasswordPolicyError):
                service.change_password(user, "some-other-current-pw", "Bootstrap-Pass-1234")
        service.users.update_user.assert_not_called()


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


class LogoutEndpointTests(unittest.TestCase):
    def test_logout_bumps_token_version(self) -> None:
        auth_service = MagicMock()
        app = FastAPI()
        app.include_router(auth_router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: make_auth_db()
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
        svc._repo.get_by_username_ci.return_value = None
        # spec so MagicMock allows the assert_* policy methods to be called.
        svc._rbac = MagicMock(spec=RBACService)
        return svc

    def test_password_reset_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, password="a-brand-new-password", actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], True)

    def test_case_variant_username_is_rejected(self) -> None:
        from core.domain_exceptions import ConflictError

        svc = self._service(_user(token_version=4))
        svc._repo.get_by_username_ci.return_value = _user(user_id=99)
        with self.assertRaises(ConflictError):
            svc.update_user(1, username="admin", actor_user_id=2)
        with self.assertRaises(ConflictError):
            svc.create_user("ADMIN", "a-brand-new-password")

    def test_username_change_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, username="renamed", actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], True)

    def test_deactivation_via_update_user_bumps(self) -> None:
        svc = self._service(_user(token_version=4))
        svc.update_user(1, is_active=False, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], True)

    def test_reactivation_does_not_bump(self) -> None:
        svc = self._service(_user(token_version=4, is_active=False))
        svc.update_user(1, is_active=True, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], False)

    def test_set_active_false_bumps(self) -> None:
        svc = self._service(_user(token_version=7))
        svc.set_active(1, False, actor_user_id=2)
        _a, kwargs = svc._repo.update_user.call_args
        self.assertIs(kwargs["bump_token_version"], True)


if __name__ == "__main__":
    unittest.main()
