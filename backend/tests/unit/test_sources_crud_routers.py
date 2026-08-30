"""TestClient coverage for the parallel source-CRUD routers
(routers/sources/{ise,mattermost,pyats}/crud.py) — happy path + the
exception -> HTTP-status mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import (
    get_ise_source_config_service,
    get_mattermost_source_config_service,
    get_pyats_source_config_service,
)
from routers.sources.ise import crud as ise_crud
from routers.sources.mattermost import crud as mm_crud
from routers.sources.pyats import crud as pyats_crud
from services.auth.rbac_service import RBACService
from services.credentials.exceptions import CredentialNameConflictError
from services.ise.source_config_service import (
    ISESourceConflictError,
    ISESourceNotFoundError,
)
from services.mattermost.source_config_service import (
    MattermostSourceConflictError,
    MattermostSourceNotFoundError,
)
from services.pyats.source_config_service import (
    PyATSSourceConflictError,
    PyATSSourceNotFoundError,
)

_RESPONSE = {"source_id": "s1", "url": "https://x", "verify_ssl": True, "timeout": 30.0}

_VARIANTS = {
    "ise": {
        "module": ise_crud,
        "dep": get_ise_source_config_service,
        "prefix": "/sources/ise",
        "not_found": ISESourceNotFoundError,
        "conflict": ISESourceConflictError,
        "create_body": {"source_id": "s1", "url": "https://x", "username": "u", "password": "p"},
    },
    "mattermost": {
        "module": mm_crud,
        "dep": get_mattermost_source_config_service,
        "prefix": "/sources/mattermost",
        "not_found": MattermostSourceNotFoundError,
        "conflict": MattermostSourceConflictError,
        "create_body": {"source_id": "s1", "url": "https://x", "token": "t"},
    },
    "pyats": {
        "module": pyats_crud,
        "dep": get_pyats_source_config_service,
        "prefix": "/sources/pyats",
        "not_found": PyATSSourceNotFoundError,
        "conflict": PyATSSourceConflictError,
        "create_body": {"source_id": "s1", "url": "https://x", "token": "t"},
    },
}


@pytest.fixture(params=list(_VARIANTS), ids=list(_VARIANTS))
def variant(request):
    return _VARIANTS[request.param]


@pytest.fixture
def client(variant, monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(variant["module"].router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    service = MagicMock()
    app.dependency_overrides[variant["dep"]] = lambda: service
    with TestClient(app) as c:
        yield c, service, variant


class TestListAndGet:
    def test_list_ok(self, client):
        c, service, v = client
        service.list_sources.return_value = [_RESPONSE]
        r = c.get(f"/api{v['prefix']}")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_list_internal_error_is_sanitised(self, client):
        c, service, v = client
        service.list_sources.side_effect = RuntimeError("boom")
        r = c.get(f"/api{v['prefix']}")
        assert r.status_code == 500
        assert set(r.json()["detail"]) == {"message", "error_id"}

    def test_get_ok(self, client):
        c, service, v = client
        service.get_source.return_value = _RESPONSE
        assert c.get(f"/api{v['prefix']}/s1").status_code == 200

    def test_get_not_found(self, client):
        c, service, v = client
        service.get_source.side_effect = v["not_found"]("missing")
        assert c.get(f"/api{v['prefix']}/s1").status_code == 404


class TestCreate:
    def test_create_ok(self, client):
        c, service, v = client
        service.create_source.return_value = _RESPONSE
        r = c.post(f"/api{v['prefix']}", json=v["create_body"])
        assert r.status_code == 201

    def test_create_conflict(self, client):
        c, service, v = client
        service.create_source.side_effect = v["conflict"]("dup")
        assert c.post(f"/api{v['prefix']}", json=v["create_body"]).status_code == 409

    def test_create_credential_conflict_maps_to_409(self, client):
        c, service, v = client
        service.create_source.side_effect = CredentialNameConflictError("dup")
        assert c.post(f"/api{v['prefix']}", json=v["create_body"]).status_code == 409

    def test_create_value_error_maps_to_400(self, client):
        c, service, v = client
        service.create_source.side_effect = ValueError("bad url")
        assert c.post(f"/api{v['prefix']}", json=v["create_body"]).status_code == 400

    def test_create_unexpected_error_is_500(self, client):
        c, service, v = client
        service.create_source.side_effect = RuntimeError("boom")
        assert c.post(f"/api{v['prefix']}", json=v["create_body"]).status_code == 500


class TestUpdateAndDelete:
    def test_update_ok(self, client):
        c, service, v = client
        service.update_source.return_value = _RESPONSE
        r = c.put(f"/api{v['prefix']}/s1", json={"url": "https://y"})
        assert r.status_code == 200

    def test_update_not_found(self, client):
        c, service, v = client
        service.update_source.side_effect = v["not_found"]("missing")
        assert c.put(f"/api{v['prefix']}/s1", json={"url": "https://y"}).status_code == 404

    def test_update_value_error(self, client):
        c, service, v = client
        service.update_source.side_effect = ValueError("bad")
        assert c.put(f"/api{v['prefix']}/s1", json={"url": "https://y"}).status_code == 400

    def test_delete_ok(self, client):
        c, service, v = client
        service.delete_source.return_value = None
        assert c.delete(f"/api{v['prefix']}/s1").status_code == 204

    def test_delete_not_found(self, client):
        c, service, v = client
        service.delete_source.side_effect = v["not_found"]("missing")
        assert c.delete(f"/api{v['prefix']}/s1").status_code == 404

    def test_delete_unexpected_error_is_500(self, client):
        c, service, v = client
        service.delete_source.side_effect = RuntimeError("boom")
        assert c.delete(f"/api{v['prefix']}/s1").status_code == 500
