"""Tests for the HTTP and Redis transports of the agent integration."""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx
from fakeredis import FakeAsyncRedis

from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from services.agents.envelope import derive_http_token, open_envelope, seal
from services.agents.exceptions import (
    AgentAuthError,
    AgentOfflineError,
    AgentTimeoutError,
    AgentTransportError,
)
from services.agents.http_transport import HttpTransport
from services.agents.redis_transport import RedisTransport

SECRET = "h" * MIN_AGENT_SECRET_LENGTH
AGENT = "agent-geo"


def _request_envelope(command_id: str = "cmd-1") -> dict:
    return seal(
        {"handler": "echo", "params": {}, "inputs": {"a": 1}},
        secret=SECRET,
        agent_id=AGENT,
        command_id=command_id,
        direction="request",
        ttl_seconds=30,
    )


def _response_envelope(command_id: str = "cmd-1") -> dict:
    return seal(
        {"status": "success", "output": {"a": 1}, "error": None},
        secret=SECRET,
        agent_id=AGENT,
        command_id=command_id,
        direction="response",
        ttl_seconds=30,
    )


class HttpTransportTests(unittest.IsolatedAsyncioTestCase):
    def _transport(self, handler) -> HttpTransport:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return HttpTransport(
            url="http://geo-agent:8080", agent_id=AGENT, secret=SECRET, client=client
        )

    async def test_posts_envelope_with_token_and_returns_response(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_response_envelope())

        transport = self._transport(handler)
        request = _request_envelope()
        response = await transport.call(request, timeout=5)

        self.assertEqual(seen["url"], "http://geo-agent:8080/v1/invoke")
        self.assertEqual(seen["auth"], f"Bearer {derive_http_token(SECRET, AGENT)}")
        self.assertEqual(seen["body"], request)
        opened = open_envelope(
            response, secret=SECRET, expected_agent_id=AGENT, expected_direction="response"
        )
        self.assertEqual(opened.payload["output"], {"a": 1})
        await transport.aclose()

    async def test_connection_failure_means_offline(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with self.assertRaises(AgentOfflineError):
            await self._transport(handler).call(_request_envelope(), timeout=5)

    async def test_read_timeout_is_a_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with self.assertRaises(AgentTimeoutError):
            await self._transport(handler).call(_request_envelope(), timeout=5)

    async def test_rejected_token_is_an_auth_error(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status), self.assertRaises(AgentAuthError):
                await self._transport(lambda r, s=status: httpx.Response(s)).call(
                    _request_envelope(), timeout=5
                )

    async def test_other_http_errors_and_garbage_are_transport_errors(self) -> None:
        for response in (
            httpx.Response(500, text="boom"),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json=["not", "an", "object"]),
        ):
            with self.subTest(status=response.status_code), self.assertRaises(AgentTransportError):
                await self._transport(lambda r, resp=response: resp).call(
                    _request_envelope(), timeout=5
                )

    async def test_oversized_response_is_refused(self) -> None:
        transport = self._transport(lambda r: httpx.Response(200, content=b"x" * 5000))
        transport._max_response_bytes = 1000
        with self.assertRaises(AgentTransportError):
            await transport.call(_request_envelope(), timeout=5)

    async def test_error_text_does_not_leak_secret_or_url_credentials(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text=f"echo {SECRET}")

        with self.assertRaises(AgentTransportError) as ctx:
            await self._transport(handler).call(_request_envelope(), timeout=5)
        self.assertNotIn(SECRET, str(ctx.exception))


class RedisTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.redis = FakeAsyncRedis(decode_responses=True)
        self.addAsyncCleanup(self.redis.aclose)
        self.transport = RedisTransport(self.redis, agent_id=AGENT)

    async def _heartbeat(self) -> None:
        await self.redis.hset(f"manus-agent:{AGENT}:hb", mapping={"status": "online"})

    async def _agent_answers(self, command_id: str = "cmd-1") -> None:
        _, raw = await self.redis.blpop([f"manus-agent:{AGENT}:req"], timeout=2)
        envelope = json.loads(raw)
        open_envelope(
            envelope, secret=SECRET, expected_agent_id=AGENT, expected_direction="request"
        )
        await self.redis.rpush(
            f"manus-agent:{AGENT}:resp:{command_id}", json.dumps(_response_envelope(command_id))
        )

    async def test_round_trip(self) -> None:
        await self._heartbeat()
        answer = asyncio.create_task(self._agent_answers())
        response = await self.transport.call(_request_envelope(), timeout=3)
        await answer
        self.assertEqual(response["command_id"], "cmd-1")
        # nothing left behind
        self.assertEqual(await self.redis.llen(f"manus-agent:{AGENT}:req"), 0)
        self.assertEqual(await self.redis.exists(f"manus-agent:{AGENT}:resp:cmd-1"), 0)

    async def test_no_heartbeat_fails_fast_without_queueing(self) -> None:
        with self.assertRaises(AgentOfflineError):
            await self.transport.call(_request_envelope(), timeout=3)
        self.assertEqual(await self.redis.llen(f"manus-agent:{AGENT}:req"), 0)

    async def test_timeout_removes_the_request_so_a_late_agent_ignores_it(self) -> None:
        await self._heartbeat()
        with self.assertRaises(AgentTimeoutError):
            await self.transport.call(_request_envelope(), timeout=0.2)
        self.assertEqual(await self.redis.llen(f"manus-agent:{AGENT}:req"), 0)

    async def test_request_queue_has_a_ttl(self) -> None:
        await self._heartbeat()
        task = asyncio.create_task(self.transport.call(_request_envelope(), timeout=0.3))
        await asyncio.sleep(0.05)
        self.assertGreater(await self.redis.ttl(f"manus-agent:{AGENT}:req"), 0)
        with self.assertRaises(AgentTimeoutError):
            await task

    async def test_a_short_call_never_shortens_the_queue_ttl_of_a_long_one(self) -> None:
        # One list serves every in-flight call. EXPIRE replaces the TTL, so a 1 s call used to
        # delete a request that a 300 s call had queued behind a busy agent.
        await self._heartbeat()
        long_call = asyncio.create_task(
            self.transport.call(_request_envelope("c-long"), timeout=300)
        )
        await asyncio.sleep(0.05)
        long_ttl = await self.redis.ttl(f"manus-agent:{AGENT}:req")
        assert long_ttl > 300
        with self.assertRaises(AgentTimeoutError):
            await self.transport.call(_request_envelope("c-short"), timeout=0.2)
        assert await self.redis.ttl(f"manus-agent:{AGENT}:req") >= long_ttl - 2
        long_call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await long_call

    async def test_a_longer_call_extends_the_queue_ttl(self) -> None:
        await self._heartbeat()
        short = asyncio.create_task(self.transport.call(_request_envelope("c-1"), timeout=5))
        await asyncio.sleep(0.05)
        before = await self.redis.ttl(f"manus-agent:{AGENT}:req")
        longer = asyncio.create_task(self.transport.call(_request_envelope("c-2"), timeout=200))
        await asyncio.sleep(0.05)
        assert await self.redis.ttl(f"manus-agent:{AGENT}:req") > before + 100
        for task in (short, longer):
            task.cancel()
        await asyncio.gather(short, longer, return_exceptions=True)

    async def test_an_oversized_response_is_refused_before_it_is_parsed(self) -> None:
        await self._heartbeat()
        self.transport._max_response_bytes = 100
        await self.redis.rpush(f"manus-agent:{AGENT}:resp:cmd-1", "x" * 500)
        with self.assertRaises(AgentTransportError) as ctx:
            await self.transport.call(_request_envelope(), timeout=2)
        assert "too large" in str(ctx.exception)

    async def test_garbage_response_is_a_transport_error(self) -> None:
        await self._heartbeat()
        await self.redis.rpush(f"manus-agent:{AGENT}:resp:cmd-1", "not json")
        with self.assertRaises(AgentTransportError):
            await self.transport.call(_request_envelope(), timeout=2)

    async def test_redis_failure_is_offline(self) -> None:
        class Broken:
            async def exists(self, *_a, **_k):
                raise ConnectionError("down")

        transport = RedisTransport(Broken(), agent_id=AGENT)  # type: ignore[arg-type]
        with self.assertRaises(AgentOfflineError):
            await transport.call(_request_envelope(), timeout=1)

    async def test_concurrent_calls_get_their_own_answers(self) -> None:
        await self._heartbeat()

        async def agent() -> None:
            for _ in range(2):
                _, raw = await self.redis.blpop([f"manus-agent:{AGENT}:req"], timeout=2)
                command_id = json.loads(raw)["command_id"]
                await self.redis.rpush(
                    f"manus-agent:{AGENT}:resp:{command_id}",
                    json.dumps(_response_envelope(command_id)),
                )

        worker = asyncio.create_task(agent())
        first, second = await asyncio.gather(
            self.transport.call(_request_envelope("c-1"), timeout=3),
            self.transport.call(_request_envelope("c-2"), timeout=3),
        )
        await worker
        self.assertEqual({first["command_id"], second["command_id"]}, {"c-1", "c-2"})


if __name__ == "__main__":
    unittest.main()
