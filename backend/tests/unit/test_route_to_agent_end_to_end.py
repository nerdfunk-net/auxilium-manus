"""route-to-agent through the real client, envelope and HTTP transport against a fake agent."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.agents.client import AgentClient
from services.agents.envelope import derive_http_token, open_envelope, seal
from services.agents.http_transport import HttpTransport
from services.agents.source_config_service import AgentConnection
from workflow_steps.route_to_agent import executor as mod
from workflow_steps.route_to_agent.executor import execute

SECRET = "e" * MIN_AGENT_SECRET_LENGTH
AGENT = "agent-geo"
CONFIG: dict[str, Any] = {
    "agent_source_id": "geo",
    "handler": "resolve_location",
    "params": {"suffix": "-site"},
    "input_paths": ["nautobot.location.name"],
    "destination_path": "agent.geo",
    "output_keys": ["location"],
}


def _connection() -> AgentConnection:
    return AgentConnection(
        source_id="geo",
        transport="http",
        agent_id=AGENT,
        url="http://geo-agent:8080",
        max_concurrency=3,
        max_request_bytes=65536,
        max_timeout_seconds=30,
        secret=SECRET,
    )


class FakeAgent:
    """What agent/example-agent/manus_agent will do: check token, open, run handler, seal the answer."""

    def __init__(self, secret: str = SECRET) -> None:
        self.secret = secret
        self.seen: list[dict[str, Any]] = []
        self.wire: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.wire.append(request.content.decode())
        expected = f"Bearer {derive_http_token(self.secret, AGENT)}"
        if request.headers.get("authorization") != expected:
            return httpx.Response(401)
        envelope = json.loads(request.content)
        opened = open_envelope(
            envelope, secret=self.secret, expected_agent_id=AGENT, expected_direction="request"
        )
        payload = opened.payload
        self.seen.append(payload)
        name = payload["inputs"]["attributes"]["nautobot.location.name"]
        answer = {
            "status": "success",
            "output": {"location": name.upper() + payload["params"]["suffix"]},
        }
        return httpx.Response(
            200,
            json=seal(
                answer,
                secret=self.secret,
                agent_id=AGENT,
                command_id=opened.command_id,
                direction="response",
                ttl_seconds=30,
            ),
        )


def _device(device_id: str, site: str) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags={"nautobot": {"location": {"name": site}}},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


async def _run(agent: FakeAgent, *devices: DeviceContext):
    def build(connection: AgentConnection) -> AgentClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(agent))
        transport = HttpTransport(
            url=connection.url or "",
            agent_id=connection.agent_id,
            secret=connection.secret,
            client=client,
        )
        return AgentClient(connection, transport)

    context = WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "resolve_agent_connection", return_value=_connection()),
        patch.object(mod.service_factory, "build_agent_client", side_effect=build),
    ):
        return await execute(
            config=dict(CONFIG),
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_answer_is_available_at_the_destination_path(self) -> None:
        agent = FakeAgent()
        outcomes = await _run(agent, _device("d1", "berlin"), _device("d2", "paris"))
        devices = outcomes[0].context.devices
        self.assertEqual(devices["d1"].attribute_bags["agent"]["geo"]["location"], "BERLIN-site")
        self.assertEqual(devices["d2"].attribute_bags["agent"]["geo"]["location"], "PARIS-site")
        self.assertEqual(
            agent.seen[0]["inputs"],
            {"attributes": {"nautobot.location.name": "berlin"}, "content": {}},
        )

    async def test_nothing_readable_crosses_the_wire(self) -> None:
        agent = FakeAgent()
        await _run(agent, _device("d1", "berlin-secret-site"))
        self.assertTrue(agent.wire)
        for message in agent.wire:
            self.assertNotIn("berlin-secret-site", message)
            self.assertNotIn("resolve_location", message)

    async def test_agent_with_another_secret_fails_every_device_as_auth_error(self) -> None:
        outcomes = await _run(FakeAgent(secret="x" * MIN_AGENT_SECRET_LENGTH), _device("d1", "a"))
        by_name = {o.name: o for o in outcomes}
        error = by_name["failure"].context.devices["d1"].errors[0]
        self.assertEqual(error.failure.kind, "auth_failed")  # type: ignore[union-attr]
        self.assertEqual(by_name["success"].context.devices, {})


if __name__ == "__main__":
    unittest.main()
