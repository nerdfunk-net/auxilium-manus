"""FP-07 backend items: required JWT claims (S1-14), refresh / OIDC-start limits (S1-12/15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from _auth_helpers import make_auth_db
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from core.auth import verify_token
from core.config import settings
from core.database import get_db
from dependencies import get_refresh_rate_limiter
from routers.auth import router as auth_router
from services.auth.login_rate_limiter import RateLimitExceededError


def _token(**claims) -> str:
    now = datetime.now(UTC)
    base = {"sub": "a", "user_id": 1, "tv": 0, "iat": now, "sid_iat": int(now.timestamp())}
    base.update(claims)
    return jwt.encode(
        {k: v for k, v in base.items() if v is not None}, settings.secret_key, algorithm="HS256"
    )


def test_token_without_exp_is_rejected() -> None:
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token())
    with pytest.raises(HTTPException) as exc:
        verify_token(creds)
    assert exc.value.status_code == 401


def test_token_with_all_claims_is_accepted() -> None:
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=_token(exp=datetime.now(UTC) + timedelta(minutes=5))
    )
    assert verify_token(creds)["sub"] == "a"


def test_access_token_expiry_bounds() -> None:
    from core.config import Settings

    with patch.dict("os.environ", {"ACCESS_TOKEN_EXPIRE_MINUTES": "0"}):
        with pytest.raises(RuntimeError, match="ACCESS_TOKEN_EXPIRE_MINUTES"):
            Settings()


def test_refresh_is_rate_limited() -> None:
    limiter = MagicMock()
    limiter.check.side_effect = [None, RateLimitExceededError("k")]
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[get_refresh_rate_limiter] = lambda: limiter
    with TestClient(app) as client:
        first = client.post("/api/auth/refresh")  # no bearer: 401 but within budget
        second = client.post("/api/auth/refresh")
    assert first.status_code == 401
    assert second.status_code == 429
