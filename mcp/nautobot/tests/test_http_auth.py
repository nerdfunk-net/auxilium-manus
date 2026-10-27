import logging

import httpx
import pytest

from nautobot_mcp.http_auth import BearerTokenMiddleware

TOKENS = {"ui": "u" * 32, "ci": "c" * 40}


async def downstream(scope, receive, send):
    if scope["type"] == "lifespan":
        message = await receive()
        assert message["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"x-seen", b"1")]})
    await send({"type": "http.response.body", "body": b"mcp"})


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=BearerTokenMiddleware(downstream, TOKENS))
    return httpx.AsyncClient(transport=transport, base_url="http://mcp.test")


async def test_valid_token_reaches_the_app(client):
    for token in TOKENS.values():
        response = await client.post("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert (response.status_code, response.text) == (200, "mcp")


async def test_scheme_is_case_insensitive(client):
    response = await client.get("/mcp", headers={"Authorization": f"bearer {TOKENS['ui']}"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "u" * 32},
        {"Authorization": "Bearer " + "u" * 31},  # a prefix of a real token
        {"Authorization": "Bearer " + "u" * 33},
    ],
)
async def test_everything_else_is_401_and_never_reaches_the_app(client, headers):
    response = await client.post("/mcp", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "unauthorized"}
    assert "x-seen" not in response.headers


async def test_healthz_needs_no_token_and_does_not_reach_the_app(client):
    response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert "x-seen" not in response.headers
    assert (await client.post("/healthz")).status_code == 401  # only GET is open


async def test_rejections_are_logged_without_any_token(client, caplog):
    caplog.set_level(logging.WARNING, logger="nautobot_mcp.http_auth")
    await client.post("/mcp", headers={"Authorization": "Bearer secret-guess-123"})
    assert "rejected" in caplog.text
    assert "secret-guess-123" not in caplog.text


async def test_accepted_requests_log_the_client_name_not_the_token(client, caplog):
    caplog.set_level(logging.DEBUG, logger="nautobot_mcp.http_auth")
    await client.post("/mcp", headers={"Authorization": f"Bearer {TOKENS['ci']}"})
    assert "client 'ci'" in caplog.text
    assert TOKENS["ci"] not in caplog.text


async def test_lifespan_scope_is_passed_through_untouched():
    app = BearerTokenMiddleware(downstream, TOKENS)
    sent = []

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        sent.append(message["type"])

    await app({"type": "lifespan"}, receive, send)
    assert sent == ["lifespan.startup.complete"]
