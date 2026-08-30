"""TestClient coverage for routers/git/{operations,version_control,debug}.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from git import GitCommandError

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.dev_tools import require_dev_tools
from core.domain_exceptions import DomainError, NotFoundError
from dependencies import (
    get_cache_service,
    get_git_auth_service,
    get_git_cache_service,
    get_git_debug_service,
    get_git_operations_service,
    get_git_version_control_service,
)
from routers.git import debug as debug_router
from routers.git import operations as ops_router
from routers.git import version_control as vc_router
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
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[require_dev_tools] = lambda: None
    return app


@pytest.fixture(autouse=True)
def _allow_rbac(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)


class TestOperationsRouter:
    @pytest.fixture
    def ctx(self):
        app = _app(ops_router.router)
        ops = MagicMock()
        app.dependency_overrides[get_git_operations_service] = lambda: ops
        app.dependency_overrides[get_git_cache_service] = lambda: MagicMock()
        with TestClient(app) as c:
            yield c, ops

    def test_status_ok(self, ctx):
        c, ops = ctx
        ops.get_status_payload.return_value = {"success": True, "data": {}}
        assert c.get("/api/git/1/status").status_code == 200

    def test_status_domain_error_propagates(self, ctx):
        c, ops = ctx
        ops.get_status_payload.side_effect = NotFoundError("no repo")
        assert c.get("/api/git/1/status").status_code == 404

    def test_status_unexpected_error_returns_soft_failure(self, ctx):
        c, ops = ctx
        ops.get_status_payload.side_effect = RuntimeError("boom")
        body = c.get("/api/git/1/status").json()
        assert body["success"] is False and "error_id" in body

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

    def test_info_ok_and_domain_error(self, ctx):
        c, ops = ctx
        ops.get_info_payload.return_value = {"id": 1}
        assert c.get("/api/git/1/info").status_code == 200
        ops.get_info_payload.side_effect = NotFoundError("nope")
        assert c.get("/api/git/1/info").status_code == 404

    def test_debug_ok_and_error(self, ctx):
        c, ops = ctx
        ops.get_debug_payload.return_value = {"status": "success"}
        assert c.get("/api/git/1/debug").status_code == 200
        ops.get_debug_payload.side_effect = RuntimeError("boom")
        assert c.get("/api/git/1/debug").status_code == 500


class TestVersionControlRouter:
    @pytest.fixture
    def ctx(self):
        app = _app(vc_router.router)
        vc = MagicMock()
        app.dependency_overrides[get_git_version_control_service] = lambda: vc
        app.dependency_overrides[get_cache_service] = lambda: MagicMock()
        with TestClient(app) as c:
            yield c, vc

    def test_branches_ok(self, ctx):
        c, vc = ctx
        vc.get_branches.return_value = [{"name": "main", "current": True}]
        assert c.get("/api/git/1/branches").status_code == 200

    def test_branches_invalid_repo_404(self, ctx):
        c, vc = ctx
        vc.get_branches.side_effect = GitCommandError("branch", 128)
        assert c.get("/api/git/1/branches").status_code == 404

    def test_branches_unexpected_500(self, ctx):
        c, vc = ctx
        vc.get_branches.side_effect = RuntimeError("boom")
        assert c.get("/api/git/1/branches").status_code == 500

    def test_commits_ok_and_value_error_404(self, ctx):
        c, vc = ctx
        vc.get_commits.return_value = [{"hash": "abc"}]
        assert c.get("/api/git/1/commits/main").status_code == 200
        vc.get_commits.side_effect = ValueError("Branch 'x' not found")
        assert c.get("/api/git/1/commits/x").status_code == 404

    def test_diff_missing_params_400(self, ctx):
        c, _vc = ctx
        assert c.post("/api/git/1/diff", json={"commit1": "a"}).status_code == 400

    def test_diff_ok(self, ctx):
        c, vc = ctx
        vc.compare_commits.return_value = {"diff_lines": []}
        r = c.post(
            "/api/git/1/diff",
            json={"commit1": "a", "commit2": "b", "file_path": "x.cfg"},
        )
        assert r.status_code == 200

    def test_diff_unexpected_500(self, ctx):
        c, vc = ctx
        vc.compare_commits.side_effect = RuntimeError("boom")
        r = c.post(
            "/api/git/1/diff",
            json={"commit1": "a", "commit2": "b", "file_path": "x.cfg"},
        )
        assert r.status_code == 500


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
