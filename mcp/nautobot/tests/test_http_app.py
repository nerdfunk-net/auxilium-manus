import asyncio
import socket

import httpx
import httpx2
import pytest
import uvicorn
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from nautobot_mcp.context import AppContext
from nautobot_mcp.http_app import build_http_app
from nautobot_mcp.http_config import HttpConfig
from nautobot_mcp.server import build_server
from nautobot_mcp.vocabularies import VocabularyCache
from tests.conftest import FakeNautobot

TOKEN = "t" * 40


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def served():
    """Run the real HTTP app (uvicorn, real socket) for the duration of one test."""

    class Running:
        async def __aenter__(self):
            self.port = free_port()
            fake = FakeNautobot()
            app = AppContext(client=fake, vocabularies=VocabularyCache(fake))
            config = HttpConfig.from_env(
                {"MCP_CLIENT_TOKENS": f"ui={TOKEN}", "MCP_PORT": str(self.port)}
            )
            asgi = build_http_app(build_server(app, instructions="hello"), config)
            self.server = uvicorn.Server(
                uvicorn.Config(asgi, host="127.0.0.1", port=self.port, log_level="warning")
            )
            self.task = asyncio.create_task(self.server.serve())
            while not self.server.started:
                await asyncio.sleep(0.01)
            self.url = f"http://127.0.0.1:{self.port}/mcp"
            return self

        async def __aexit__(self, *exc):
            self.server.should_exit = True
            await self.task

    return Running()


async def test_authorised_client_lists_and_calls_tools_over_real_http(served):
    async with served:
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"})
        async with Client(streamable_http_client(served.url, http_client=http)) as client:
            assert client.instructions == "hello"
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"list_devices", "list_locations", "list_prefixes"} <= names
            result = await client.call_tool("list_roles", {"content_type": "dcim.device"})
            assert not result.is_error
        await http.aclose()


async def test_requests_without_or_with_a_wrong_token_get_401(served):
    async with served, httpx.AsyncClient() as http:
        body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = await http.post(served.url, json=body, headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"


async def test_health_endpoint_is_open_and_reports_ok(served):
    async with served, httpx.AsyncClient() as http:
        response = await http.get(f"http://127.0.0.1:{served.port}/healthz")
        assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_unexpected_host_header_is_rejected_even_with_a_valid_token(served):
    async with served, httpx.AsyncClient() as http:
        response = await http.post(
            served.url,
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Host": "evil.example",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 421
