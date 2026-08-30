"""TestClient coverage for routers/git/repositories.py (repo config CRUD)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_git_connection_service, get_git_repository_service
from models.git_repositories import GitConnectionTestResponse
from routers.git.repositories import router as repo_router
from services.auth.rbac_service import RBACService

_REPO = {
    "id": 1,
    "name": "configs",
    "category": "device_configs",
    "url": "https://example.com/c.git",
    "branch": "main",
    "auth_type": "token",
    "credential_name": None,
    "path": None,
    "verify_ssl": True,
    "git_author_name": None,
    "git_author_email": None,
    "description": None,
    "is_active": True,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "last_sync": None,
    "sync_status": None,
}
_CREATE_BODY = {"name": "configs", "category": "device_configs", "url": "https://example.com/c.git"}


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(repo_router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    svc = MagicMock()
    conn = MagicMock()
    app.dependency_overrides[get_git_repository_service] = lambda: svc
    app.dependency_overrides[get_git_connection_service] = lambda: conn
    with TestClient(app) as client:
        yield client, svc, conn


class TestReadRoutes:
    def test_list_ok(self, ctx):
        client, svc, _ = ctx
        svc.get_repositories.return_value = [_REPO, _REPO]
        r = client.get("/api/git-repositories")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_list_error_sanitised(self, ctx):
        client, svc, _ = ctx
        svc.get_repositories.side_effect = RuntimeError("boom")
        r = client.get("/api/git-repositories")
        assert r.status_code == 500
        assert set(r.json()["detail"]) == {"message", "error_id"}

    def test_get_ok_and_404(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = _REPO
        assert client.get("/api/git-repositories/1").status_code == 200
        svc.get_repository.return_value = None
        assert client.get("/api/git-repositories/1").status_code == 404

    def test_get_for_edit_ok_and_404(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = _REPO
        assert client.get("/api/git-repositories/1/edit").status_code == 200
        svc.get_repository.return_value = None
        assert client.get("/api/git-repositories/1/edit").status_code == 404

    # NOTE: GET /git-repositories/health is shadowed by GET /{repo_id} (int
    # validation -> 422) both here and in the real app; not covered on purpose.


class TestCreateRoute:
    def test_create_ok(self, ctx):
        client, svc, _ = ctx
        svc.create_repository.return_value = 1
        svc.get_repository.return_value = _REPO
        assert client.post("/api/git-repositories", json=_CREATE_BODY).status_code == 200

    def test_create_value_error_400(self, ctx):
        client, svc, _ = ctx
        svc.create_repository.side_effect = ValueError("name exists")
        assert client.post("/api/git-repositories", json=_CREATE_BODY).status_code == 400

    def test_create_missing_after_create_is_500(self, ctx):
        client, svc, _ = ctx
        svc.create_repository.return_value = 1
        svc.get_repository.return_value = None
        assert client.post("/api/git-repositories", json=_CREATE_BODY).status_code == 500

    def test_create_unexpected_error_500(self, ctx):
        client, svc, _ = ctx
        svc.create_repository.side_effect = RuntimeError("boom")
        assert client.post("/api/git-repositories", json=_CREATE_BODY).status_code == 500


class TestUpdateAndDelete:
    def test_update_ok(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.side_effect = [_REPO, _REPO]
        svc.update_repository.return_value = True
        assert client.put("/api/git-repositories/1", json={"branch": "dev"}).status_code == 200

    def test_update_404_when_absent(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = None
        assert client.put("/api/git-repositories/1", json={"branch": "dev"}).status_code == 404

    def test_update_no_fields_400(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = _REPO
        assert client.put("/api/git-repositories/1", json={}).status_code == 400

    def test_update_value_error_400(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = _REPO
        svc.update_repository.side_effect = ValueError("dup")
        assert client.put("/api/git-repositories/1", json={"name": "x"}).status_code == 400

    def test_delete_ok(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = _REPO
        svc.delete_repository.return_value = True
        assert client.delete("/api/git-repositories/1").status_code == 200

    def test_delete_404_when_absent(self, ctx):
        client, svc, _ = ctx
        svc.get_repository.return_value = None
        assert client.delete("/api/git-repositories/1").status_code == 404


class TestConnectionRoute:
    def test_test_connection_ok(self, ctx):
        client, _svc, conn = ctx
        conn.test_connection.return_value = GitConnectionTestResponse(success=True, message="ok")
        r = client.post(
            "/api/git-repositories/test-connection",
            json={"url": "https://example.com/c.git", "branch": "main", "auth_type": "none"},
        )
        assert r.status_code == 200

    def test_test_connection_reraises_exception(self, ctx):
        client, _svc, conn = ctx
        conn.test_connection.side_effect = RuntimeError("boom")
        # The endpoint logs and re-raises; the app has no handler so it surfaces.
        with pytest.raises(RuntimeError):
            client.post(
                "/api/git-repositories/test-connection",
                json={"url": "https://example.com/c.git", "branch": "main", "auth_type": "none"},
            )
