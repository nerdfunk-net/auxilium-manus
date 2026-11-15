import json
import unittest
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

from manus_agent.inventory_config import NautobotSettings
from manus_agent.nautobot import PAGE_SIZE, NautobotError, fetch_prefixes_by_tag

TOKEN = "super-secret-token"


class FakeNautobot:
    """A GraphQL endpoint whose behaviour each test chooses."""

    def __init__(self, prefixes: list[str] | None = None) -> None:
        self.prefixes = prefixes or []
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.status = 200
        self.body: Any = None  # a fixed answer overriding the prefixes
        self.delay = 0.0

    async def handle(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.requests.append(payload)
        self.headers.append(dict(request.headers))
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        if self.status != 200:
            return web.Response(status=self.status, text=f"boom {TOKEN}")
        if self.body is not None:
            return web.Response(text=json.dumps(self.body), content_type="application/json")
        variables = payload["variables"]
        start = variables["offset"]
        rows = [{"prefix": p} for p in self.prefixes[start : start + variables["limit"]]]
        return web.json_response({"data": {"prefixes": rows}})


class NautobotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fake = FakeNautobot(["192.168.178.0/24"])
        app = web.Application()
        app.router.add_post("/api/graphql/", self.fake.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)

    def settings(self, **overrides: Any) -> NautobotSettings:
        values: dict[str, Any] = {
            "url": f"http://127.0.0.1:{self.server.port}",
            "token": TOKEN,
            "timeout_seconds": 2,
            "max_prefixes": 100,
        }
        values.update(overrides)
        return NautobotSettings(**values)

    async def test_returns_the_prefixes_and_sends_the_tag_as_a_variable(self) -> None:
        assert await fetch_prefixes_by_tag(self.settings(), "ping") == ["192.168.178.0/24"]
        request = self.fake.requests[0]
        assert request["variables"]["tag"] == ["ping"]
        assert "ping" not in request["query"]  # never inside the query text
        assert "prefixes(tags: $tag" in request["query"]
        assert self.fake.headers[0]["Authorization"] == f"Token {TOKEN}"

    async def test_a_hostile_tag_stays_a_variable(self) -> None:
        tag = '"}) { __schema { types { name } } } #'
        await fetch_prefixes_by_tag(self.settings(), tag)
        request = self.fake.requests[0]
        assert request["variables"]["tag"] == [tag]
        assert "__schema" not in request["query"]

    async def test_pages_until_a_short_page(self) -> None:
        self.fake.prefixes = [f"10.{i // 250}.{i % 250}.0/24" for i in range(PAGE_SIZE + 5)]
        found = await fetch_prefixes_by_tag(self.settings(max_prefixes=1000), "ping")
        assert len(found) == PAGE_SIZE + 5
        assert [r["variables"]["offset"] for r in self.fake.requests] == [0, PAGE_SIZE]

    async def test_no_prefix_is_an_empty_list(self) -> None:
        self.fake.prefixes = []
        assert await fetch_prefixes_by_tag(self.settings(), "ping") == []

    async def test_more_than_max_prefixes_is_an_error(self) -> None:
        self.fake.prefixes = ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24"]
        with self.assertRaisesRegex(NautobotError, "more than 2 prefixes"):
            await fetch_prefixes_by_tag(self.settings(max_prefixes=2), "ping")

    async def test_http_errors_never_echo_the_body_or_the_token(self) -> None:
        for status in (401, 500):
            self.fake.status = status
            with self.subTest(status=status), self.assertRaises(NautobotError) as caught:
                await fetch_prefixes_by_tag(self.settings(), "ping")
            assert str(status) in str(caught.exception)
            assert TOKEN not in str(caught.exception) and "boom" not in str(caught.exception)

    async def test_graphql_errors_are_not_empty_results(self) -> None:
        self.fake.body = {"errors": [{"message": "secret detail"}], "data": {"prefixes": []}}
        with self.assertRaisesRegex(NautobotError, "reported an error") as caught:
            await fetch_prefixes_by_tag(self.settings(), "ping")
        assert "secret detail" not in str(caught.exception)

    async def test_malformed_answers(self) -> None:
        for body, pattern in (
            ([], "not a JSON object"),
            ({"data": None}, "no prefix list"),
            ({"data": {"prefixes": "x"}}, "no prefix list"),
            ({"data": {"prefixes": [{"nope": 1}]}}, "without a prefix"),
            ({"data": {"prefixes": ["10.0.0.0/24"]}}, "without a prefix"),
            ({"data": {"prefixes": [{"prefix": ""}]}}, "without a prefix"),
        ):
            self.fake.body = body
            with self.subTest(body=body), self.assertRaisesRegex(NautobotError, pattern):
                await fetch_prefixes_by_tag(self.settings(), "ping")

    async def test_invalid_json_is_an_error(self) -> None:
        async def garbage(request: web.Request) -> web.Response:
            return web.Response(text="<html>")

        app = web.Application()
        app.router.add_post("/api/graphql/", garbage)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        with self.assertRaisesRegex(NautobotError, "invalid data"):
            await fetch_prefixes_by_tag(
                self.settings(url=f"http://127.0.0.1:{server.port}"), "ping"
            )

    async def test_unreachable_server(self) -> None:
        with self.assertRaisesRegex(NautobotError, "could not be reached"):
            await fetch_prefixes_by_tag(self.settings(url="http://127.0.0.1:1"), "ping")

    async def test_timeout(self) -> None:
        self.fake.delay = 1.0
        with self.assertRaisesRegex(NautobotError, "in time"):
            await fetch_prefixes_by_tag(self.settings(timeout_seconds=0.2), "ping")

    async def test_redirects_are_not_followed(self) -> None:
        async def redirect(request: web.Request) -> web.Response:
            raise web.HTTPFound("http://127.0.0.1:1/elsewhere")

        app = web.Application()
        app.router.add_post("/api/graphql/", redirect)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        with self.assertRaisesRegex(NautobotError, "HTTP 302"):
            await fetch_prefixes_by_tag(
                self.settings(url=f"http://127.0.0.1:{server.port}"), "ping"
            )


class ResolverUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_name_resolving_to_a_metadata_address_never_gets_the_token(self) -> None:
        from unittest.mock import AsyncMock, patch

        settings = NautobotSettings(url="http://nautobot.internal:8080", token=TOKEN)
        blocked = AsyncMock(
            return_value=[
                {
                    "hostname": "x",
                    "host": "169.254.169.254",
                    "port": 8080,
                    "family": 2,
                    "proto": 6,
                    "flags": 0,
                }
            ]
        )
        with (
            patch("aiohttp.resolver.ThreadedResolver.resolve", blocked),
            self.assertRaisesRegex(NautobotError, "could not be reached") as caught,
        ):
            await fetch_prefixes_by_tag(settings, "ping")
        assert TOKEN not in str(caught.exception)
        blocked.assert_awaited()
