"""TestClient coverage for routers/git/{operations,debug}.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.dev_tools import require_dev_tools
from core.domain_exceptions import DomainError
from core.models.users import User
from dependencies import (
    get_git_auth_service,
    get_git_cache_service,
    get_git_debug_service,
    get_git_operations_service,
)
from routers.git import debug as debug_router
from routers.git import operations as ops_router
from services.auth.rbac_service import RBACService
from services.git.operations import SyncExecutionError


def _app(*routers) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain(_req, exc):  # noqa: ANN001
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    for r in routers:
        app.include_router(r, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: _current_user()
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[require_dev_tools] = lambda: None
    return app


@pytest.fixture(autouse=True)
def _allow_rbac(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)



def _current_user() -> User:
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    return user


class TestOperationsRouter:
    @pytest.fixture
    def ctx(self):
        app = _app(ops_router.router)
        ops = MagicMock()
        app.dependency_overrides[get_git_operations_service] = lambda: ops
        app.dependency_overrides[get_git_cache_service] = lambda: MagicMock()
        with TestClient(app) as c:
            yield c, ops

    def test_sync_ok(self, ctx):
        c, ops = ctx
        ops.sync_and_record.return_value = {"success": True}
        assert c.post("/api/git/1/sync").status_code == 200

    def test_sync_execution_error_is_sanitised_500(self, ctx):
        c, ops = ctx
        ops.sync_and_record.side_effect = SyncExecutionError("err-1", "sync failed")
        r = c.post("/api/git/1/sync")
        assert r.status_code == 500
        assert r.json()["detail"]["error_id"] == "err-1"

    def test_sync_generic_error_is_500(self, ctx):
        c, ops = ctx
        ops.sync_and_record.side_effect = RuntimeError("boom")
        assert c.post("/api/git/1/sync").status_code == 500

    def test_remove_and_sync_ok_and_error(self, ctx):
        c, ops = ctx
        ops.remove_and_sync_and_record.return_value = {"success": True}
        assert c.post("/api/git/1/remove-and-sync").status_code == 200
        ops.remove_and_sync_and_record.side_effect = SyncExecutionError("e2", "x")
        assert c.post("/api/git/1/remove-and-sync").status_code == 500


class TestDebugRouter:
    @pytest.fixture
    def ctx(self):
        app = _app(debug_router.router)
        dbg = MagicMock()
        app.dependency_overrides[get_git_debug_service] = lambda: dbg
        app.dependency_overrides[get_git_auth_service] = lambda: MagicMock()
        with TestClient(app) as c:
            yield c, dbg

    def test_read_write_delete_ok(self, ctx):
        c, dbg = ctx
        dbg.test_read.return_value = {"success": True}
        dbg.test_write.return_value = {"success": True}
        dbg.test_delete.return_value = {"success": True}
        assert c.post("/api/git-repositories/1/debug/read").status_code == 200
        assert c.post("/api/git-repositories/1/debug/write").status_code == 200
        assert c.post("/api/git-repositories/1/debug/delete").status_code == 200

    def test_read_value_error_404(self, ctx):
        c, dbg = ctx
        dbg.test_read.side_effect = ValueError("Repository 1 not found")
        assert c.post("/api/git-repositories/1/debug/read").status_code == 404

    def test_write_unexpected_500(self, ctx):
        c, dbg = ctx
        dbg.test_write.side_effect = RuntimeError("boom")
        assert c.post("/api/git-repositories/1/debug/write").status_code == 500

    def test_push_ok_and_error(self, ctx):
        c, dbg = ctx
        dbg.test_push.return_value = {"success": True}
        assert c.post("/api/git-repositories/1/debug/push").status_code == 200
        dbg.test_push.side_effect = ValueError("nope")
        assert c.post("/api/git-repositories/1/debug/push").status_code == 404

    def test_diagnostics_ok_and_error(self, ctx):
        c, dbg = ctx
        dbg.get_diagnostics.return_value = {"success": True}
        assert c.get("/api/git-repositories/1/debug/diagnostics").status_code == 200
        dbg.get_diagnostics.side_effect = RuntimeError("boom")
        assert c.get("/api/git-repositories/1/debug/diagnostics").status_code == 500
