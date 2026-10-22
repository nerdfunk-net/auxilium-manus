"""The backend's client, transports and step against the real reference agent (agent/).

The agent has its own copy of the envelope and knows nothing of the backend, so these tests are
what proves the two implementations speak the same protocol: over a real HTTP socket and over
Redis (heartbeat and status included).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
from aiohttp.test_utils import TestServer
from fakeredis import FakeAsyncRedis

REPO = Path(__file__).resolve().parents[3]


def _load_agent_package() -> None:
    """Import ``manus_agent`` without putting agent/ on sys.path.

    The agent has a regular top-level ``tests`` package; on sys.path it would win over the
    backend's namespace ``tests`` package and break every ``tests.unit`` import.
    """
    package_dir = REPO / "agent" / "manus_agent"
    spec = importlib.util.spec_from_file_location(
        "manus_agent",
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["manus_agent"] = module
    spec.loader.exec_module(module)


_load_agent_package()

from manus_agent.config import AgentConfig  # noqa: E402
from manus_agent.core import AgentCore  # noqa: E402
from manus_agent.http_server import create_app  # noqa: E402
from manus_agent.main import build_registry  # noqa: E402
from manus_agent.redis_worker import RedisWorker  # noqa: E402

from core.secret_policy import MIN_AGENT_SECRET_LENGTH  # noqa: E402
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext  # noqa: E402
from services.agents.client import AgentClient  # noqa: E402
from services.agents.exceptions import AgentAuthError, AgentHandlerError, AgentOfflineError  # noqa: E402
from services.agents.http_transport import HttpTransport  # noqa: E402
from services.agents.redis_transport import RedisTransport  # noqa: E402
from services.agents.source_config_service import AgentConnection  # noqa: E402
from services.agents.status import read_status  # noqa: E402
from workflow_steps.route_to_agent import executor as step_executor  # noqa: E402

SECRET = "i" * MIN_AGENT_SECRET_LENGTH
AGENT_ID = "geo-agent"


def _agent_config(**overrides: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "agent_id": AGENT_ID,
        "secret": SECRET,
        "http_host": "127.0.0.1",
        "http_port": 1,
        "redis_url": None,
        "handlers_dir": REPO / "agent" / "handlers",
        "max_concurrency": 4,
        "max_body_bytes": 1_048_576,
        "max_response_bytes": 1_048_576,
        "loglevel": "INFO",
    }
    values.update(overrides)
    return AgentConfig(**values)


def _connection(transport: str, url: str | None = None, secret: str = SECRET) -> AgentConnection:
    return AgentConnection(
        source_id="geo",
        transport=transport,  # type: ignore[arg-type]
        agent_id=AGENT_ID,
        url=url,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        max_timeout_seconds=30,
        secret=secret,
    )


class HttpInteropTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config = _agent_config()
        self.config = config
        self.core = AgentCore(config, build_registry(config))
        self.server = TestServer(create_app(self.core, config))
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.url = str(self.server.make_url("")).rstrip("/")

    def client(self, secret: str = SECRET) -> AgentClient:
        conn = _connection("http", self.url, secret)
        return AgentClient(
            conn, HttpTransport(url=self.url, agent_id=AGENT_ID, secret=secret)
        )

    async def test_echo_round_trip(self) -> None:
        client = self.client()
        self.addAsyncCleanup(client.aclose)
        assert await client.invoke("echo", {}, {"nonce": "abc123"}) == {"nonce": "abc123"}

    async def test_example_handler(self) -> None:
        client = self.client()
        self.addAsyncCleanup(client.aclose)
        inputs = {"attributes": {"nautobot.location.name": "Berlin-DC1"}, "content": {}}
        output = await client.invoke("resolve_location", {}, inputs)
        assert output == {"location": "Berlin"}

    async def test_handler_errors_reach_the_backend_as_handler_errors(self) -> None:
        client = self.client()
        self.addAsyncCleanup(client.aclose)
        with self.assertRaises(AgentHandlerError) as ctx:
            await client.invoke(
                "resolve_location", {"strict": True}, {"attributes": {}, "content": {}}
            )
        assert ctx.exception.error_type == "ValueError"
        with self.assertRaises(AgentHandlerError) as ctx:
            await client.invoke("does_not_exist", {}, {})
        assert ctx.exception.error_type == "UnknownHandler"

    async def test_a_different_secret_is_an_auth_error_on_both_sides(self) -> None:
        client = self.client(secret="x" * MIN_AGENT_SECRET_LENGTH)
        self.addAsyncCleanup(client.aclose)
        with self.assertRaises(AgentAuthError):
            await client.invoke("echo", {}, {})

    async def test_the_step_enriches_devices_through_the_real_agent(self) -> None:
        def build(connection: AgentConnection) -> AgentClient:
            return self.client()

        def device(device_id: str, site: str) -> DeviceContext:
            return DeviceContext(
                id=device_id,
                name=device_id,
                hostname=device_id,
                attribute_bags={"nautobot": {"location": {"name": site}}},
                capabilities={Capability.IDENTITY},
                status=DeviceStatus.OK,
            )

        context = WorkflowContext(
            run_id="r",
            workflow_id="w",
            devices={"d1": device("d1", "Berlin-DC1"), "d2": device("d2", "Paris_Edge")},
        )
        config = {
            "agent_source_id": "geo",
            "handler": "resolve_location",
            "input_paths": ["nautobot.location.name"],
            "destination_path": "agent.geo",
            "output_keys": ["location"],
        }
        with (
            patch.object(step_executor, "object_session", return_value=MagicMock()),
            patch.object(
                step_executor,
                "resolve_agent_connection",
                return_value=_connection("http", self.url),
            ),
            patch.object(step_executor.service_factory, "build_agent_client", side_effect=build),
        ):
            outcomes = await step_executor.execute(
                config=config,
                context=context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        devices = outcomes[0].context.devices
        assert devices["d1"].attribute_bags["agent"]["geo"]["location"] == "Berlin"
        assert devices["d2"].attribute_bags["agent"]["geo"]["location"] == "Paris"
        assert [o.name for o in outcomes] == ["success"]


class RedisInteropTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.redis = FakeAsyncRedis(decode_responses=True)
        self.addAsyncCleanup(self.redis.aclose)
        self.config = _agent_config(http_port=None, redis_url="redis://fake")
        self.registry = build_registry(self.config)
        self.worker = RedisWorker(
            AgentCore(self.config, self.registry),
            self.config,
            self.registry,
            self.redis,
            heartbeat_interval=0.1,
            poll_timeout=0.1,
        )
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.worker.run(self.stop))
        self.addAsyncCleanup(self._shutdown)
        for _ in range(100):
            if await self.redis.exists(f"manus-agent:{AGENT_ID}:hb"):
                break
            await asyncio.sleep(0.02)

    async def _shutdown(self) -> None:
        self.stop.set()
        await asyncio.wait_for(self.task, 5)

    def client(self, secret: str = SECRET) -> AgentClient:
        return AgentClient(
            _connection("redis", secret=secret), RedisTransport(self.redis, agent_id=AGENT_ID)  # type: ignore[arg-type]
        )

    async def test_echo_and_example_handler_over_redis(self) -> None:
        client = self.client()
        assert await client.invoke("echo", {}, {"nonce": "n1"}) == {"nonce": "n1"}
        inputs = {"attributes": {"nautobot.location.name": "Hamburg-1"}, "content": {}}
        output = await client.invoke("resolve_location", {}, inputs)
        assert output == {"location": "Hamburg"}

    async def test_a_secret_mismatch_never_gets_an_answer(self) -> None:
        # The agent cannot authenticate the request, so it stays silent; the app times out.
        from services.agents.exceptions import AgentTimeoutError

        client = self.client(secret="x" * MIN_AGENT_SECRET_LENGTH)
        with self.assertRaises(AgentTimeoutError):
            await client.invoke("echo", {}, {}, timeout=0.5)

    async def test_the_backend_status_view_reads_the_agents_heartbeat(self) -> None:
        status = await read_status(_connection("redis"), redis=self.redis)  # type: ignore[arg-type]
        assert status.online is True
        assert status.version == self.config.version
        assert "resolve_location" in status.handlers and "echo" in status.handlers
        assert status.last_heartbeat is not None and abs(status.last_heartbeat - time.time()) < 5

    async def test_a_stopped_agent_is_offline_for_the_backend(self) -> None:
        self.stop.set()
        await asyncio.wait_for(self.task, 5)
        status = await read_status(_connection("redis"), redis=self.redis)  # type: ignore[arg-type]
        assert status.online is False
        with self.assertRaises(AgentOfflineError):
            await self.client().invoke("echo", {}, {})


class RawHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_real_server_rejects_a_missing_token_before_parsing(self) -> None:
        config = _agent_config()
        server = TestServer(create_app(AgentCore(config, build_registry(config)), config))
        await server.start_server()
        self.addAsyncCleanup(server.close)
        async with httpx.AsyncClient() as http:
            response = await http.post(str(server.make_url("/v1/invoke")), json={"v": 1})
        assert response.status_code == 401


if __name__ == "__main__":
    unittest.main()
