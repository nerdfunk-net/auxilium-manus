"""Tests for AgentClient: envelope handling, limits and error mapping on top of a transport."""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import patch

from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from services.agents.client import AgentClient
from services.agents.envelope import open_envelope, seal
from services.agents.exceptions import (
    AgentAuthError,
    AgentHandlerError,
    AgentPayloadTooLargeError,
    AgentTimeoutError,
    AgentTransportError,
    AgentValidationError,
)
from services.agents.source_config_service import AgentConnection

SECRET = "c" * MIN_AGENT_SECRET_LENGTH
AGENT = "agent-geo"


def _connection(**overrides: Any) -> AgentConnection:
    values: dict[str, Any] = {
        "source_id": "geo",
        "transport": "http",
        "agent_id": AGENT,
        "url": "http://geo-agent:8080",
        "max_concurrency": 4,
        "max_request_bytes": 4096,
        "max_timeout_seconds": 30,
        "secret": SECRET,
    }
    values.update(overrides)
    return AgentConnection(**values)


class FakeTransport:
    """Plays the agent: opens the request, answers with ``reply(payload)``."""

    def __init__(
        self,
        reply,
        *,
        secret: str = SECRET,
        answer_command_id: str | None = None,
        answered_at: int | None = None,
    ):
        self.reply = reply
        self.secret = secret
        self.answer_command_id = answer_command_id
        self.answered_at = answered_at
        self.requests: list[dict] = []
        self.timeouts: list[float] = []
        self.closed = False

    async def call(self, envelope: dict, *, timeout: float) -> dict:
        self.timeouts.append(timeout)
        opened = open_envelope(
            envelope, secret=SECRET, expected_agent_id=AGENT, expected_direction="request"
        )
        self.requests.append(opened.payload)
        reply = self.reply(opened.payload)
        if isinstance(reply, Exception):
            raise reply
        return seal(
            reply,
            secret=self.secret,
            agent_id=AGENT,
            command_id=self.answer_command_id or opened.command_id,
            direction="response",
            ttl_seconds=30,
            now=self.answered_at,
        )

    async def aclose(self) -> None:
        self.closed = True


def _ok(payload: dict) -> dict:
    return {"status": "success", "output": {"location": "Berlin"}, "error": None}


class AgentClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoke_returns_output_and_sends_the_agreed_payload(self) -> None:
        transport = FakeTransport(_ok)
        client = AgentClient(_connection(), transport)
        output = await client.invoke("resolve_location", {"p": 1}, {"nautobot.site": "x"})
        self.assertEqual(output, {"location": "Berlin"})
        self.assertEqual(
            transport.requests,
            [{"handler": "resolve_location", "params": {"p": 1}, "inputs": {"nautobot.site": "x"}}],
        )

    async def test_timeout_is_clamped_to_the_agent_limit(self) -> None:
        transport = FakeTransport(_ok)
        client = AgentClient(_connection(max_timeout_seconds=10), transport)
        await client.invoke("h", {}, {}, timeout=999)
        await client.invoke("h", {}, {})
        await client.invoke("h", {}, {}, timeout=3)
        self.assertEqual(transport.timeouts, [10, 10, 3])

    async def test_oversized_request_is_refused_before_sending(self) -> None:
        transport = FakeTransport(_ok)
        client = AgentClient(_connection(max_request_bytes=1024), transport)
        with self.assertRaises(AgentPayloadTooLargeError):
            await client.invoke("h", {}, {"blob": "x" * 2000})
        self.assertEqual(transport.requests, [])

    async def test_non_json_inputs_are_a_validation_error(self) -> None:
        client = AgentClient(_connection(), FakeTransport(_ok))
        with self.assertRaises(AgentValidationError):
            await client.invoke("h", {}, {"x": object()})

    async def test_handler_name_is_validated(self) -> None:
        client = AgentClient(_connection(), FakeTransport(_ok))
        for bad in ("", "has space", "a/b", "x" * 65, "../etc"):
            with self.subTest(handler=bad), self.assertRaises(AgentValidationError):
                await client.invoke(bad, {}, {})

    async def test_agent_reported_error(self) -> None:
        def reply(payload):
            return {
                "status": "error",
                "output": None,
                "error": {"type": "KeyError", "message": "site missing " + "x" * 500},
            }

        client = AgentClient(_connection(), FakeTransport(reply))
        with self.assertRaises(AgentHandlerError) as ctx:
            await client.invoke("h", {}, {})
        self.assertEqual(ctx.exception.error_type, "KeyError")
        self.assertLessEqual(len(str(ctx.exception)), 300)

    async def test_response_signed_with_another_secret_is_an_auth_error(self) -> None:
        transport = FakeTransport(_ok, secret="z" * MIN_AGENT_SECRET_LENGTH)
        with self.assertRaises(AgentAuthError):
            await AgentClient(_connection(), transport).invoke("h", {}, {})

    async def test_a_late_answer_is_a_timeout_not_an_auth_error(self) -> None:
        # Sealed in the past, so it has expired by the time the app opens it. That says nothing
        # about the secret; treating it as auth failure would fail every other device too.
        transport = FakeTransport(_ok, answered_at=int(time.time()) - 3600)
        with self.assertRaises(AgentTimeoutError):
            await AgentClient(_connection(), transport).invoke("h", {}, {})

    async def test_an_unusable_payload_is_a_transport_error_not_an_auth_error(self) -> None:
        from services.agents.envelope import EnvelopePayloadError

        transport = FakeTransport(_ok)
        with (
            patch("services.agents.client.open_envelope", side_effect=EnvelopePayloadError("x")),
            self.assertRaises(AgentTransportError),
        ):
            await AgentClient(_connection(), transport).invoke("h", {}, {})

    async def test_response_to_another_command_is_an_auth_error(self) -> None:
        transport = FakeTransport(_ok, answer_command_id="someone-elses")
        with self.assertRaises(AgentAuthError):
            await AgentClient(_connection(), transport).invoke("h", {}, {})

    async def test_malformed_reply_payloads(self) -> None:
        for reply in (
            {"status": "weird"},
            {"status": "success", "output": ["not", "a", "dict"]},
            {"status": "success"},
            {"status": "error", "error": "not a dict"},
        ):
            with self.subTest(reply=reply), self.assertRaises(
                (AgentTransportError, AgentHandlerError)
            ):
                await AgentClient(_connection(), FakeTransport(lambda p, r=reply: r)).invoke(
                    "h", {}, {}
                )

    async def test_transport_errors_propagate(self) -> None:
        transport = FakeTransport(lambda p: AgentTimeoutError("slow"))
        with self.assertRaises(AgentTimeoutError):
            await AgentClient(_connection(), transport).invoke("h", {}, {})

    async def test_context_manager_closes_the_transport(self) -> None:
        transport = FakeTransport(_ok)
        async with AgentClient(_connection(), transport):
            pass
        self.assertTrue(transport.closed)


if __name__ == "__main__":
    unittest.main()
