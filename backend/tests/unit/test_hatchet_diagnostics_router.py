"""Permission gating of the Hatchet operator diagnostics endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import AccessDeniedError, DomainError
from core.models.users import User
from models.hatchet import HatchetRunDiagnostics, HatchetWorkersResponse
from routers import hatchet_settings
from services.auth.rbac_service import RBACService


def _user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _db() -> Iterator[MagicMock]:
    yield make_auth_db()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(hatchet_settings.router, prefix="/api")

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    with (
        patch("core.rate_limit.service_factory.build_user_rate_limiter", return_value=MagicMock()),
        TestClient(app) as test_client,
    ):
        yield test_client


def test_workers_forbidden_without_permission(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    assert client.get("/api/hatchet/workers").status_code == 403


def test_run_diagnostics_forbidden_without_permission(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    assert client.get("/api/hatchet/runs/1").status_code == 403


def test_workers_allowed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    payload = HatchetWorkersResponse(engine_reachable=True, message="OK")
    with patch.object(
        hatchet_settings.HatchetDiagnosticsService,
        "get_workers",
        AsyncMock(return_value=payload),
    ):
        response = client.get("/api/hatchet/workers")
    assert response.status_code == 200
    assert response.json()["engine_reachable"] is True


def test_run_diagnostics_checks_run_access_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run service's own visibility check runs before the engine is asked anything."""
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    diagnostics = AsyncMock()
    with (
        patch.object(
            hatchet_settings.RunService, "get_run", side_effect=AccessDeniedError("no access")
        ),
        patch.object(
            hatchet_settings.HatchetDiagnosticsService, "get_run_diagnostics", diagnostics
        ),
    ):
        response = client.get("/api/hatchet/runs/1")
    assert response.status_code == 403
    diagnostics.assert_not_called()


def test_run_diagnostics_allowed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    payload = HatchetRunDiagnostics(engine_reachable=True, message="OK", engine_status="RUNNING")
    with (
        patch.object(hatchet_settings.RunService, "get_run", return_value=MagicMock()),
        patch.object(
            hatchet_settings.HatchetDiagnosticsService,
            "get_run_diagnostics",
            AsyncMock(return_value=payload),
        ),
    ):
        response = client.get("/api/hatchet/runs/1")
    assert response.status_code == 200
    assert response.json()["engine_status"] == "RUNNING"


def test_db_session_is_released_before_the_engine_is_asked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    order: list[str] = []
    db = make_auth_db()
    db.commit = MagicMock(side_effect=lambda: order.append("commit"))
    client.app.dependency_overrides[get_db] = lambda: db  # type: ignore[union-attr]

    async def _diagnose(*_a: object, **_k: object) -> HatchetRunDiagnostics:
        order.append("engine")
        return HatchetRunDiagnostics(engine_reachable=True, message="OK")

    with (
        patch.object(hatchet_settings.RunService, "get_run", return_value=MagicMock()),
        patch.object(hatchet_settings.HatchetDiagnosticsService, "get_run_diagnostics", _diagnose),
    ):
        assert client.get("/api/hatchet/runs/1").status_code == 200
    assert order == ["commit", "engine"]
