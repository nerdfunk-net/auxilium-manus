import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from manus_agent.core import AgentCore
from manus_agent.envelope import derive_http_token
from manus_agent.http_server import create_app
from tests.helpers import (
    AGENT,
    NOW,
    SECRET,
    make_config,
    make_registry,
    open_response,
    request_envelope,
)

TOKEN = derive_http_token(SECRET, AGENT)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class HttpServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = make_config(max_body_bytes=4096)
        self.core = AgentCore(self.config, make_registry(), clock=lambda: NOW)
        self.client = TestClient(TestServer(create_app(self.core, self.config)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def post(self, body, headers=AUTH, raw: bytes | None = None):
        data = raw if raw is not None else json.dumps(body).encode()
        return await self.client.post(
            "/v1/invoke", data=data, headers={**headers, "Content-Type": "application/json"}
        )

    async def test_round_trip(self) -> None:
        response = await self.post(request_envelope())
        assert response.status == 200
        assert response.content_type == "application/json"
        assert open_response(await response.json()) == {
            "status": "success",
            "output": {"v": "BERLIN"},
        }

    async def test_handler_errors_are_ordinary_200_answers(self) -> None:
        response = await self.post(request_envelope("boom"))
        assert response.status == 200
        assert open_response(await response.json())["status"] == "error"

    async def test_missing_or_wrong_token_is_401_and_nothing_runs(self) -> None:
        calls = []
        self.core.handle = lambda envelope: calls.append(envelope)  # type: ignore[method-assign]
        bad_headers = (
            {},
            {"Authorization": "Bearer nope"},
            {"Authorization": TOKEN},  # no scheme
            {"Authorization": "Basic abc"},
        )
        for headers in bad_headers:
            response = await self.post(request_envelope(), headers=headers)
            assert response.status == 401, headers
            assert response.headers.get("WWW-Authenticate") == "Bearer"
        assert calls == []

    async def test_valid_token_with_a_forged_envelope_is_403(self) -> None:
        response = await self.post(request_envelope(secret="z" * 40))
        assert response.status == 403
        assert "z" * 40 not in await response.text()

    async def test_replay_is_409(self) -> None:
        envelope = request_envelope()
        assert (await self.post(envelope)).status == 200
        assert (await self.post(envelope)).status == 409

    async def test_invalid_bodies_are_400(self) -> None:
        for raw in (b"not json", b"[1, 2]", b'"text"', b"null"):
            response = await self.post(None, raw=raw)
            assert response.status == 400, raw

    async def test_oversized_body_is_413(self) -> None:
        response = await self.post(None, raw=b'{"x": "' + b"a" * 10_000 + b'"}')
        assert response.status == 413

    async def test_healthz_needs_no_token_and_reveals_nothing(self) -> None:
        response = await self.client.get("/healthz")
        assert response.status == 200
        assert await response.json() == {"status": "ok"}

    async def test_only_post_is_allowed_on_invoke(self) -> None:
        assert (await self.client.get("/v1/invoke", headers=AUTH)).status == 405

    async def test_unknown_paths_are_404(self) -> None:
        assert (await self.client.get("/v1/handlers", headers=AUTH)).status == 404


if __name__ == "__main__":
    unittest.main()
