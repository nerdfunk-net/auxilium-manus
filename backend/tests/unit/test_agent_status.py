"""Tests for services.agents.status (heartbeat view of an agent) and the status route."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_agent_source_config_service
from routers.sources.agent import ops as agent_ops
from services.agents.redis_transport import heartbeat_key
from services.agents.source_config_service import AgentConnection, AgentSourceNotFoundError
from services.agents.status import AgentStatus, read_status
from services.auth.rbac_service import RBACService


def _connection(transport: str = "redis") -> AgentConnection:
    return AgentConnection(
        source_id="geo",
        transport=transport,  # type: ignore[arg-type]
        agent_id="agent-geo",
        url="http://geo:8080" if transport == "http" else None,
        max_concurrency=4,
        max_request_bytes=1024,
        max_timeout_seconds=30,
        secret="s" * 40,
    )


class ReadStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.redis = FakeAsyncRedis(decode_responses=True)
        self.addAsyncCleanup(self.redis.aclose)

    async def test_online_agent_reports_version_and_handlers(self) -> None:
        now = int(time.time())
        await self.redis.hset(
            heartbeat_key("agent-geo"),
            mapping={
                "status": "online",
                "version": "1.2.0",
                "handlers": "echo,resolve_location",
                "last_heartbeat": now,
            },
        )
        status = await read_status(_connection(), redis=self.redis)
        self.assertEqual(status.online, True)
        self.assertEqual(status.version, "1.2.0")
        self.assertEqual(status.handlers, ["echo", "resolve_location"])
        self.assertEqual(status.last_heartbeat, now)

    async def test_missing_heartbeat_is_offline(self) -> None:
        status = await read_status(_connection(), redis=self.redis)
        self.assertEqual(status.online, False)
        self.assertEqual(status.handlers, [])

    async def test_http_agents_have_no_heartbeat(self) -> None:
        status = await read_status(_connection("http"), redis=None)
        self.assertIsNone(status.online)
        self.assertIn("Test connection", status.message)

    async def test_redis_failure_is_unknown_not_an_exception(self) -> None:
        class Broken:
            async def hgetall(self, *_a, **_k):
                raise ConnectionError("down")

        status = await read_status(_connection(), redis=Broken())  # type: ignore[arg-type]
        self.assertIsNone(status.online)
        self.assertNotIn("down", status.message)

    async def test_malformed_values_do_not_break_the_view(self) -> None:
        await self.redis.hset(
            heartbeat_key("agent-geo"), mapping={"last_heartbeat": "yesterday", "handlers": ""}
        )
        status = await read_status(_connection(), redis=self.redis)
        self.assertTrue(status.online)
        self.assertIsNone(status.last_heartbeat)
        self.assertEqual(status.handlers, [])


_URL = "/api/sources/agent/geo/status"


def _client(monkeypatch, *, allowed: bool = True):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: allowed)
    app = FastAPI()
    app.include_router(agent_ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    service = MagicMock()
    service.resolve_connection.return_value = _connection()
    app.dependency_overrides[get_agent_source_config_service] = lambda: service
    return TestClient(app), service


def test_status_route_returns_the_view(monkeypatch):
    async def fake(connection):
        return AgentStatus(
            transport="redis", online=True, version="1", handlers=["echo"],
            last_heartbeat=5, message="Agent is online.",
        )

    monkeypatch.setattr(agent_ops.service_factory, "read_agent_status", fake)
    c, _ = _client(monkeypatch)
    with c:
        body = c.get(_URL).json()
    assert body["online"] is True and body["handlers"] == ["echo"]
    assert "secret" not in str(body).lower()


def test_status_route_errors_and_permission(monkeypatch):
    c, service = _client(monkeypatch)
    with c:
        service.resolve_connection.side_effect = AgentSourceNotFoundError("nope")
        assert c.get(_URL).status_code == 404
    c, _ = _client(monkeypatch, allowed=False)
    with c:
        assert c.get(_URL).status_code == 403


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
