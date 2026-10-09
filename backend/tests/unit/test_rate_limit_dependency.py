"""core.rate_limit.rate_limited: per-user budget, 429 + Retry-After, Redis-down fallback (S9)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import redis
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import service_factory
from core.auth import get_current_user
from core.models.users import User
from core.rate_limit import rate_limited


def _user(user_id: int) -> User:
    user = User(username=f"u{user_id}", password_hash="h", is_active=True)
    user.id = user_id
    return user


def _app(current: dict) -> FastAPI:
    app = FastAPI()

    budget = rate_limited("test-bucket", attempts=3, window_seconds=60)

    @app.get("/x", dependencies=[Depends(budget)])
    def endpoint() -> dict:
        return {"ok": True}

    app.dependency_overrides[get_current_user] = lambda: current["user"]
    return app


@pytest.fixture(autouse=True)
def _redis_down():
    """Redis is 'down' for these tests, so the in-process window does the counting."""
    target = "services.auth.login_rate_limiter.LoginRateLimiter"
    with (
        patch(f"{target}._check_and_record_redis", side_effect=redis.RedisError("down")),
    ):
        yield


def test_allows_up_to_budget_then_429() -> None:
    current = {"user": _user(1)}
    with TestClient(_app(current)) as client:
        statuses = [client.get("/x").status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_budget_is_per_user() -> None:
    current = {"user": _user(1)}
    with TestClient(_app(current)) as client:
        for _ in range(3):
            assert client.get("/x").status_code == 200
        assert client.get("/x").status_code == 429
        current["user"] = _user(2)
        assert client.get("/x").status_code == 200


def test_429_has_retry_after() -> None:
    current = {"user": _user(1)}
    with TestClient(_app(current)) as client:
        for _ in range(3):
            client.get("/x")
        response = client.get("/x")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_redis_down_falls_back_in_process() -> None:
    # The autouse fixture makes Redis raise; the endpoint must still serve (fail-open
    # to the in-process window) rather than 500/429 on the first call.
    current = {"user": _user(1)}
    with TestClient(_app(current)) as client:
        assert client.get("/x").status_code == 200
    limiter = service_factory.build_user_rate_limiter("test-bucket", 3, 60)
    assert limiter is service_factory.build_user_rate_limiter("test-bucket", 3, 60)


def test_reusing_a_bucket_with_a_different_budget_fails_at_definition() -> None:
    rate_limited("budget-conflict-bucket", attempts=5, window_seconds=60)
    rate_limited("budget-conflict-bucket", attempts=5, window_seconds=60)  # same budget is fine
    with pytest.raises(ValueError):
        rate_limited("budget-conflict-bucket", attempts=6, window_seconds=60)
