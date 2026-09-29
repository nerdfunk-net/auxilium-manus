"""CacheSettingsService.rebuild + POST /api/cache/rebuild."""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import ConflictError
from core.models.users import User
from models.cache_settings import CacheRebuildResponse
from routers.cache_settings import router as cache_router
from services.auth.rbac_service import RBACService
from services.cache.cache_settings_service import CacheSettingsService


def _service(*, enabled: bool = True, cache=MagicMock()) -> CacheSettingsService:
    svc = CacheSettingsService(MagicMock(), cache)
    svc._repo = MagicMock()
    svc._repo.get_by_key.return_value = MagicMock(
        value={"enabled": enabled, "device_ttl_seconds": 1800, "location_ttl_seconds": 600}
    )
    return svc


def _trigger(run_id: str = "hatchet-run-1"):
    return patch(
        "hatchet.workflows.cache_devices.rebuild_workflow.run_no_wait",
        return_value=MagicMock(workflow_run_id=run_id),
    )


class RebuildServiceTests(unittest.TestCase):
    def test_starts_the_rebuild_workflow_and_returns_its_run_id(self) -> None:
        with _trigger("abc") as run_no_wait:
            response = _service().rebuild()

        run_no_wait.assert_called_once()
        self.assertEqual(response, CacheRebuildResponse(started=True, hatchet_run_id="abc"))

    def test_refuses_when_redis_is_not_connected(self) -> None:
        with _trigger() as run_no_wait, self.assertRaises(ConflictError) as ctx:
            _service(cache=None).rebuild()

        self.assertIn("Redis", ctx.exception.detail)
        run_no_wait.assert_not_called()

    def test_refuses_when_caching_is_disabled(self) -> None:
        with _trigger() as run_no_wait, self.assertRaises(ConflictError) as ctx:
            _service(enabled=False).rebuild()

        self.assertIn("disabled", ctx.exception.detail.lower())
        run_no_wait.assert_not_called()

    def test_engine_failure_is_a_generic_500_without_leaking_the_cause(self) -> None:
        with (
            patch(
                "hatchet.workflows.cache_devices.rebuild_workflow.run_no_wait",
                side_effect=RuntimeError("grpc://secret-host:7077 refused"),
            ),
            self.assertRaises(HTTPException) as ctx,
        ):
            _service().rebuild()

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertNotIn("secret-host", str(ctx.exception.detail))


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(cache_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


def test_rebuild_requires_auth() -> None:
    bare = FastAPI()
    bare.include_router(cache_router, prefix="/api")
    with TestClient(bare) as client:
        assert client.post("/api/cache/rebuild").status_code == 401


def test_rebuild_forbidden_without_write_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)

    with TestClient(app) as client:
        response = client.post("/api/cache/rebuild")

    assert response.status_code == 403
    assert "cache_settings:write" in response.json()["detail"]


def test_rebuild_returns_started_and_run_id(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    service = MagicMock()
    service.rebuild.return_value = CacheRebuildResponse(started=True, hatchet_run_id="r-9")
    monkeypatch.setattr("routers.cache_settings.CacheSettingsService", lambda db, cache: service)
    monkeypatch.setattr("service_factory.build_cache_service", lambda: None)

    with TestClient(app) as client:
        response = client.post("/api/cache/rebuild")

    assert response.status_code == 200
    assert response.json() == {"started": True, "hatchet_run_id": "r-9"}


def test_rebuild_conflict_is_a_409(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.domain_exceptions import DomainError
    from main import domain_error_handler

    app.add_exception_handler(DomainError, domain_error_handler)
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    service = MagicMock()
    service.rebuild.side_effect = ConflictError("Redis is not connected")
    monkeypatch.setattr("routers.cache_settings.CacheSettingsService", lambda db, cache: service)
    monkeypatch.setattr("service_factory.build_cache_service", lambda: None)

    with TestClient(app) as client:
        response = client.post("/api/cache/rebuild")

    assert response.status_code == 409
    assert response.json() == {"detail": "Redis is not connected"}


if __name__ == "__main__":
    unittest.main()
