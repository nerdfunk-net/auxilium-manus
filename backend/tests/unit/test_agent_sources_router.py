"""TestClient coverage for routers/sources/agent/crud.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_agent_source_config_service
from routers.sources.agent import crud as agent_crud
from services.agents.exceptions import AgentValidationError
from services.agents.source_config_service import (
    AgentSourceConflictError,
    AgentSourceNotFoundError,
)
from services.auth.rbac_service import RBACService

_RESPONSE = {
    "source_id": "geo",
    "transport": "http",
    "agent_id": "agent-geo",
    "url": "http://geo-agent:8080",
    "credential_id": 5,
    "credential_name": "geo-agent-key",
    "max_concurrency": 4,
    "max_request_bytes": 1048576,
    "max_timeout_seconds": 60,
}
_CREATE_BODY = {
    "source_id": "geo",
    "transport": "http",
    "agent_id": "agent-geo",
    "url": "http://geo-agent:8080",
    "credential_id": 5,
}
_PREFIX = "/api/sources/agent"


def _make_client(monkeypatch, *, allowed: bool = True):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: allowed)
    app = FastAPI()
    app.include_router(agent_crud.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    service = MagicMock()
    app.dependency_overrides[get_agent_source_config_service] = lambda: service
    return TestClient(app), service


@pytest.fixture
def client(monkeypatch):
    c, service = _make_client(monkeypatch)
    with c:
        yield c, service


def test_list_and_get(client):
    c, service = client
    service.list_sources.return_value = [_RESPONSE]
    service.get_source.return_value = _RESPONSE
    listing = c.get(_PREFIX)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "secret" not in str(listing.json()).lower().replace("credential", "")
    assert c.get(f"{_PREFIX}/geo").status_code == 200


def test_get_not_found(client):
    c, service = client
    service.get_source.side_effect = AgentSourceNotFoundError("nope")
    assert c.get(f"{_PREFIX}/nope").status_code == 404


def test_create_passes_every_field_to_the_service(client):
    c, service = client
    service.create_source.return_value = _RESPONSE
    r = c.post(
        _PREFIX,
        json={
            **_CREATE_BODY,
            "max_concurrency": 2,
            "max_request_bytes": 2048,
            "max_timeout_seconds": 9,
        },
    )
    assert r.status_code == 201
    assert service.create_source.call_args.kwargs == {
        "source_id": "geo",
        "transport": "http",
        "agent_id": "agent-geo",
        "url": "http://geo-agent:8080",
        "credential_id": 5,
        "max_concurrency": 2,
        "max_request_bytes": 2048,
        "max_timeout_seconds": 9,
    }


def test_create_maps_domain_errors(client):
    c, service = client
    service.create_source.side_effect = AgentSourceConflictError("geo")
    assert c.post(_PREFIX, json=_CREATE_BODY).status_code == 409
    service.create_source.side_effect = AgentValidationError("bad url")
    assert c.post(_PREFIX, json=_CREATE_BODY).status_code == 400
    service.create_source.side_effect = RuntimeError("boom")
    r = c.post(_PREFIX, json=_CREATE_BODY)
    assert r.status_code == 500
    assert set(r.json()["detail"]) == {"message", "error_id"}


def test_unknown_fields_are_rejected(client):
    c, _ = client
    assert c.post(_PREFIX, json={**_CREATE_BODY, "secret": "x" * 40}).status_code == 422
    assert c.put(f"{_PREFIX}/geo", json={"password": "x"}).status_code == 422


def test_invalid_bodies_are_rejected_before_the_service(client):
    c, service = client
    for patch_ in (
        {"source_id": "Bad Id"},
        {"transport": "smtp"},
        {"max_concurrency": 0},
        {"credential_id": 0},
    ):
        assert c.post(_PREFIX, json={**_CREATE_BODY, **patch_}).status_code == 422, patch_
    service.create_source.assert_not_called()


def test_update_and_delete(client):
    c, service = client
    service.update_source.return_value = _RESPONSE
    assert c.put(f"{_PREFIX}/geo", json={"max_concurrency": 8}).status_code == 200
    assert service.update_source.call_args.args == ("geo",)
    assert service.update_source.call_args.kwargs["max_concurrency"] == 8
    service.update_source.side_effect = AgentValidationError("bad")
    assert c.put(f"{_PREFIX}/geo", json={"url": "http://x"}).status_code == 400
    service.delete_source.return_value = None
    assert c.delete(f"{_PREFIX}/geo").status_code == 204
    service.delete_source.side_effect = AgentSourceNotFoundError("geo")
    assert c.delete(f"{_PREFIX}/geo").status_code == 404


def test_requires_permission(monkeypatch):
    c, service = _make_client(monkeypatch, allowed=False)
    with c:
        assert c.get(_PREFIX).status_code == 403
        assert c.post(_PREFIX, json=_CREATE_BODY).status_code == 403
        assert c.delete(f"{_PREFIX}/geo").status_code == 403
    service.list_sources.assert_not_called()
