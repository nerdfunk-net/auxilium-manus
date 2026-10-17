"""TestClient coverage for routers/rbac/permissions.py: a duplicate permission is a 409."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import ConflictError, DomainError
from core.models.users import User
from routers.rbac.permissions import _service
from routers.rbac.permissions import router as permissions_router
from services.auth.rbac_service import RBACService

_DT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(permissions_router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    svc = MagicMock()
    app.dependency_overrides[_service] = lambda: svc
    with TestClient(app) as client:
        yield client, svc


def test_duplicate_permission_is_409(ctx):
    client, svc = ctx
    svc.create_permission.side_effect = ConflictError("Permission a:b already exists")
    response = client.post("/api/rbac/permissions", json={"resource": "a", "action": "b"})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_create_permission_ok(ctx):
    client, svc = ctx
    svc.create_permission.return_value = SimpleNamespace(
        id=1, resource="a", action="b", description=None, created_at=_DT
    )
    response = client.post("/api/rbac/permissions", json={"resource": "a", "action": "b"})
    assert response.status_code == 201
