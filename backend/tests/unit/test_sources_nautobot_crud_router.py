"""TestClient coverage for routers/sources/nautobot/crud.py (saved inventories)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_inventory_service
from routers.sources.nautobot.crud import router as crud_router
from services.auth.rbac_service import RBACService

_INV = {
    "id": 1,
    "name": "prod",
    "description": None,
    "conditions": [],
    "inventory_type": "filter",
    "device_ids": [],
    "template_category": None,
    "template_name": None,
    "scope": "global",
    "group_path": None,
    "created_by": "t",
    "is_active": True,
    "created_at": None,
    "updated_at": None,
}


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(crud_router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    svc = MagicMock()
    app.dependency_overrides[get_inventory_service] = lambda: svc
    with TestClient(app) as client:
        yield client, svc


class TestCreateInventory:
    def test_create_ok(self, ctx):
        client, svc = ctx
        svc.create_inventory.return_value = 1
        svc.get_inventory.return_value = _INV
        r = client.post("/api/sources/nautobot", json={"name": "prod", "conditions": []})
        assert r.status_code == 201
        assert r.json()["name"] == "prod"

    def test_create_returns_500_when_id_missing(self, ctx):
        client, svc = ctx
        svc.create_inventory.return_value = None
        r = client.post("/api/sources/nautobot", json={"name": "prod"})
        assert r.status_code == 500

    def test_create_value_error_maps_to_400(self, ctx):
        client, svc = ctx
        svc.create_inventory.side_effect = ValueError("dup name")
        r = client.post("/api/sources/nautobot", json={"name": "prod"})
        assert r.status_code == 400

    def test_create_unexpected_error_sanitised_500(self, ctx):
        client, svc = ctx
        svc.create_inventory.side_effect = RuntimeError("db down")
        r = client.post("/api/sources/nautobot", json={"name": "prod"})
        assert r.status_code == 500
        assert set(r.json()["detail"]) == {"message", "error_id"}


class TestListAndSearch:
    def test_list_ok(self, ctx):
        client, svc = ctx
        svc.list_inventories.return_value = [_INV, _INV]
        r = client.get("/api/sources/nautobot?scope=global")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_list_error_sanitised(self, ctx):
        client, svc = ctx
        svc.list_inventories.side_effect = RuntimeError("boom")
        assert client.get("/api/sources/nautobot").status_code == 500

    def test_search_ok(self, ctx):
        client, svc = ctx
        svc.search_inventories.return_value = [_INV]
        r = client.get("/api/sources/nautobot/search/prod")
        assert r.status_code == 200
        assert r.json()["total"] == 1


class TestGet:
    def test_get_by_name_ok(self, ctx):
        client, svc = ctx
        svc.get_inventory_by_name.return_value = _INV
        assert client.get("/api/sources/nautobot/by-name/prod").status_code == 200

    def test_get_by_name_404(self, ctx):
        client, svc = ctx
        svc.get_inventory_by_name.return_value = None
        assert client.get("/api/sources/nautobot/by-name/ghost").status_code == 404

    def test_get_by_id_ok(self, ctx):
        client, svc = ctx
        svc.get_inventory.return_value = _INV
        assert client.get("/api/sources/nautobot/1").status_code == 200

    def test_get_by_id_404(self, ctx):
        client, svc = ctx
        svc.get_inventory.return_value = None
        assert client.get("/api/sources/nautobot/9").status_code == 404

    def test_get_by_id_permission_error_maps_to_403(self, ctx):
        client, svc = ctx
        svc.get_inventory.side_effect = PermissionError("not yours")
        assert client.get("/api/sources/nautobot/9").status_code == 403


class TestUpdateAndDelete:
    def test_update_ok(self, ctx):
        client, svc = ctx
        svc.update_inventory.return_value = True
        svc.get_inventory.return_value = _INV
        r = client.put("/api/sources/nautobot/1", json={"name": "renamed", "group_path": "a/b"})
        assert r.status_code == 200

    def test_update_missing_after_update_404(self, ctx):
        client, svc = ctx
        svc.update_inventory.return_value = True
        svc.get_inventory.return_value = None
        assert client.put("/api/sources/nautobot/1", json={"name": "x"}).status_code == 404

    def test_update_value_error_400(self, ctx):
        client, svc = ctx
        svc.update_inventory.side_effect = ValueError("permission")
        assert client.put("/api/sources/nautobot/1", json={"name": "x"}).status_code == 400

    def test_delete_hard_ok(self, ctx):
        client, svc = ctx
        svc.delete_inventory.return_value = True
        r = client.delete("/api/sources/nautobot/1")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_soft_ok(self, ctx):
        client, svc = ctx
        svc.delete_inventory.return_value = True
        r = client.delete("/api/sources/nautobot/1?hard_delete=false")
        assert "deactivated" in r.json()["message"]

    def test_delete_value_error_400(self, ctx):
        client, svc = ctx
        svc.delete_inventory.side_effect = ValueError("not found")
        assert client.delete("/api/sources/nautobot/1").status_code == 400

    def test_delete_unexpected_error_500(self, ctx):
        client, svc = ctx
        svc.delete_inventory.side_effect = RuntimeError("boom")
        assert client.delete("/api/sources/nautobot/1").status_code == 500
