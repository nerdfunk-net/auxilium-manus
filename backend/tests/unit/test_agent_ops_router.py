"""TestClient coverage for routers/sources/agent/ops.py (test-connection)."""

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
from routers.sources.agent import ops as agent_ops
from services.agents.exceptions import (
    AgentAuthError,
    AgentHandlerError,
    AgentOfflineError,
    AgentTimeoutError,
    AgentValidationError,
)
from services.agents.source_config_service import AgentSourceNotFoundError
from services.auth.rbac_service import RBACService

_URL = "/api/sources/agent/test-connection"


class _FakeClient:
    """Stands in for AgentClient: ``behaviour`` decides what the echo call does."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls: list[tuple] = []
        self.closed = False

    async def invoke(self, handler, params, inputs, *, timeout=None):
        self.calls.append((handler, params, inputs, timeout))
        return self.behaviour(inputs)

    async def aclose(self):
        self.closed = True


def _make(monkeypatch, behaviour, *, allowed: bool = True):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: allowed)
    fake = _FakeClient(behaviour)
    monkeypatch.setattr(agent_ops.service_factory, "build_agent_client", lambda conn: fake)
    app = FastAPI()
    app.include_router(agent_ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    service = MagicMock()
    service.resolve_connection.return_value = MagicMock(max_timeout_seconds=60)
    app.dependency_overrides[get_agent_source_config_service] = lambda: service
    return TestClient(app), service, fake


def _raise(exc):
    def behaviour(_inputs):
        raise exc

    return behaviour


def test_success_echoes_a_fresh_nonce(monkeypatch):
    c, service, fake = _make(monkeypatch, lambda inputs: dict(inputs))
    with c:
        r = c.post(_URL, json={"source_id": "geo"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert isinstance(body["latency_ms"], int)
    handler, params, inputs, _ = fake.calls[0]
    assert handler == "echo" and params == {}
    assert len(inputs["nonce"]) >= 16
    assert fake.closed
    service.resolve_connection.assert_called_once_with("geo")


def test_wrong_echo_is_reported_as_failure(monkeypatch):
    c, _, _ = _make(monkeypatch, lambda inputs: {"nonce": "something-else"})
    with c:
        body = c.post(_URL, json={"source_id": "geo"}).json()
    assert body["success"] is False
    assert "echo" in body["message"].lower()


@pytest.mark.parametrize(
    ("exc", "fragment"),
    [
        (AgentOfflineError("raw internal detail"), "not reachable"),
        (AgentTimeoutError("raw internal detail"), "did not answer"),
        (AgentAuthError("raw internal detail"), "secret"),
        (AgentHandlerError("KeyError", "raw internal detail"), "echo"),
        (RuntimeError("raw internal detail"), "failed"),
    ],
)
def test_failures_give_a_fixed_message_never_the_raw_error(monkeypatch, exc, fragment):
    c, _, fake = _make(monkeypatch, _raise(exc))
    with c:
        r = c.post(_URL, json={"source_id": "geo"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert fragment in body["message"].lower()
    assert "raw internal detail" not in body["message"]
    assert fake.closed


def test_unknown_source_and_invalid_source(monkeypatch):
    c, service, _ = _make(monkeypatch, lambda i: i)
    with c:
        service.resolve_connection.side_effect = AgentSourceNotFoundError("nope")
        assert c.post(_URL, json={"source_id": "nope"}).status_code == 404
        service.resolve_connection.side_effect = AgentValidationError("short secret")
        assert c.post(_URL, json={"source_id": "geo"}).status_code == 400


def test_body_is_validated(monkeypatch):
    c, _, _ = _make(monkeypatch, lambda i: i)
    with c:
        assert c.post(_URL, json={}).status_code == 422
        assert c.post(_URL, json={"source_id": "geo", "url": "http://x"}).status_code == 422


def test_requires_write_permission(monkeypatch):
    c, service, fake = _make(monkeypatch, lambda i: i, allowed=False)
    with c:
        assert c.post(_URL, json={"source_id": "geo"}).status_code == 403
    service.resolve_connection.assert_not_called()
    assert fake.calls == []

