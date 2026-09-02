"""Tests for JWT session refresh (keepalive)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import settings
from core.database import get_db
from core.models.users import User
from routers.auth import router as auth_router
from services.auth.auth_service import AuthenticationError, AuthService
from services.auth.rbac_service import RBACService


def _make_user(
    *, user_id: int = 1, username: str = "alice", is_active: bool = True, token_version: int = 0
) -> User:
    user = User(username=username, password_hash="hash", is_active=is_active)
    user.id = user_id
    user.token_version = token_version
    return user


def _make_expired_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.username,
        "user_id": user.id,
        "iat": int((now - timedelta(minutes=5)).timestamp()),
        "sid_iat": int((now - timedelta(minutes=5)).timestamp()),
        "tv": user.token_version,
        "exp": now - timedelta(minutes=5),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _make_invalid_signature_token(user: User) -> str:
    payload = {
        "sub": user.username,
        "user_id": user.id,
        "exp": datetime.now(UTC) + timedelta(minutes=30),
    }
    # >= 32 bytes — PyJWT warns on shorter HS256 keys (RFC 7518 §3.2).
    return jwt.encode(payload, "wrong-secret-key-for-tests-only!!", algorithm="HS256")


class TestAuthServiceRefresh:
    def test_refresh_valid_token_returns_new_token(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        original_token, _ = service.create_access_token(user)
        refreshed_user, new_token, expires_in = service.refresh_access_token(original_token)

        assert refreshed_user is user
        assert isinstance(new_token, str)
        assert expires_in == settings.access_token_expire_minutes * 60
        payload = jwt.decode(new_token, settings.secret_key, algorithms=["HS256"])
        assert payload["sub"] == "alice"
        assert payload["user_id"] == 1

    def test_refresh_accepts_expired_signed_token(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        expired_token = _make_expired_token(user)
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(expired_token, settings.secret_key, algorithms=["HS256"])

        refreshed_user, new_token, _expires_in = service.refresh_access_token(expired_token)

        assert refreshed_user is user
        jwt.decode(new_token, settings.secret_key, algorithms=["HS256"])

    def test_refresh_rejects_invalid_signature(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(_make_invalid_signature_token(user))

    def test_refresh_rejects_inactive_user(self) -> None:
        user = _make_user(is_active=False)
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user
        token, _ = service.create_access_token(user)

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)

    def test_refresh_rejects_missing_user(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = None
        token = _make_expired_token(user)

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)

    def test_refresh_rejects_token_expired_beyond_max_age(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        max_age = timedelta(hours=settings.refresh_token_max_age_hours, minutes=1)
        payload = {
            "sub": user.username,
            "user_id": user.id,
            "exp": datetime.now(UTC) - max_age,
        }
        stale_token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(stale_token)

    def test_refresh_preserves_sid_iat(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        started = datetime.now(UTC) - timedelta(hours=2)
        original, _ = service.create_access_token(user, sid_iat=started)
        _u, refreshed, _e = service.refresh_access_token(original)

        assert (
            jwt.decode(refreshed, settings.secret_key, algorithms=["HS256"])["sid_iat"]
            == jwt.decode(original, settings.secret_key, algorithms=["HS256"])["sid_iat"]
        )

    def test_refresh_rejects_when_session_max_age_exceeded(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        started = datetime.now(UTC) - timedelta(hours=settings.session_max_age_hours + 1)
        # Build the token directly so create_access_token's own cap does not fire early.
        payload = {
            "sub": user.username,
            "user_id": user.id,
            "iat": int(started.timestamp()),
            "sid_iat": int(started.timestamp()),
            "tv": user.token_version,
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)

    def test_refresh_rejects_stale_token_version(self) -> None:
        user = _make_user(token_version=1)
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        token, _ = service.create_access_token(user)  # tv = 1
        user.token_version = 2  # a bump happened after the token was minted

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)

    def test_refresh_rejects_token_without_tv(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "sid_iat": int(datetime.now(UTC).timestamp()),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)

    def test_refresh_rejects_token_without_sid_iat(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "tv": user.token_version,
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(token)


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def refresh_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    user = _make_user()
    auth_service = AuthService(MagicMock())
    auth_service.users = MagicMock()
    auth_service.users.get_by_id.return_value = user

    monkeypatch.setattr(
        "routers.auth.AuthService",
        lambda db: auth_service,
    )
    monkeypatch.setattr(
        RBACService,
        "get_user_roles",
        lambda self, _user_id: ["admin"],
    )
    monkeypatch.setattr(
        RBACService,
        "get_user_permission_strings",
        lambda self, _user_id: ["workflows:read"],
    )

    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.dependency_overrides[get_db] = _override_db
    app.state.auth_service = auth_service  # type: ignore[attr-defined]
    app.state.user = user  # type: ignore[attr-defined]
    return app


def test_refresh_endpoint_returns_session_for_valid_token(refresh_app: FastAPI) -> None:
    auth_service: AuthService = refresh_app.state.auth_service  # type: ignore[attr-defined]
    user: User = refresh_app.state.user  # type: ignore[attr-defined]
    token, _ = auth_service.create_access_token(user)

    with TestClient(refresh_app) as client:
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "access_token" in payload
    assert payload["expires_in"] == settings.access_token_expire_minutes * 60
    assert payload["user"]["username"] == "alice"
    assert payload["user"]["roles"] == ["admin"]
    assert payload["user"]["permissions"] == ["workflows:read"]


def test_refresh_endpoint_accepts_expired_token(refresh_app: FastAPI) -> None:
    user: User = refresh_app.state.user  # type: ignore[attr-defined]
    expired_token = _make_expired_token(user)

    with TestClient(refresh_app) as client:
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "alice"


def test_refresh_endpoint_rejects_missing_auth(refresh_app: FastAPI) -> None:
    with TestClient(refresh_app) as client:
        response = client.post("/api/auth/refresh")

    assert response.status_code == 401


def test_refresh_endpoint_rejects_invalid_token(refresh_app: FastAPI) -> None:
    user: User = refresh_app.state.user  # type: ignore[attr-defined]

    with TestClient(refresh_app) as client:
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {_make_invalid_signature_token(user)}"},
        )

    assert response.status_code == 401
