"""S2-02: approving needs workflows:execute and takes no deploy_workflow_id."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.change_requests import _service
from routers.change_requests import router as cr_router
from services.auth.rbac_service import RBACService


@pytest.fixture
def ctx(monkeypatch):
    held = {("change_requests", "approve")}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, uid, r, a: (r, a) in held)
    app = FastAPI()
    app.include_router(cr_router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    service = MagicMock()
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service, held


def test_approve_requires_workflows_execute(ctx) -> None:
    client, service, held = ctx
    assert client.post("/api/change-requests/5/approve").status_code == 403
    service.approve.assert_not_called()
    held.add(("workflows", "execute"))
    client.post("/api/change-requests/5/approve")
    service.approve.assert_called_once_with(5, actor_user_id=1, via="ui")


def test_approve_body_with_deploy_workflow_id_is_422(ctx) -> None:
    client, service, held = ctx
    held.add(("workflows", "execute"))
    response = client.post("/api/change-requests/5/approve", json={"deploy_workflow_id": 7})
    assert response.status_code == 422
    service.approve.assert_not_called()
