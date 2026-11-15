"""HTTP transport: ``POST /v1/invoke`` with the sealed envelope as the JSON body.

The bearer token is derived from the shared secret and lets the server drop unauthenticated
traffic before it parses anything; the envelope is what protects the content. Error bodies are
fixed sentences: they never echo the request, the token or the secret.
"""

from __future__ import annotations

import hmac
import logging

from aiohttp import web

from manus_agent.config import AgentConfig
from manus_agent.core import AgentCore, RequestRejected
from manus_agent.envelope import derive_http_token

logger = logging.getLogger(__name__)

_REJECTION_STATUS = {"unauthenticated": 403, "replay": 409, "malformed": 400}
_REJECTION_TEXT = {
    "unauthenticated": "message authentication failed",
    "replay": "message was already processed",
    "malformed": "malformed message",
}


def _bearer(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def create_app(core: AgentCore, config: AgentConfig) -> web.Application:
    expected = derive_http_token(config.secret, config.agent_id).encode()

    async def invoke(request: web.Request) -> web.Response:
        supplied = _bearer(request)
        if supplied is None or not hmac.compare_digest(supplied.encode(), expected):
            return web.json_response(
                {"error": "missing or invalid bearer token"},
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "body must be a JSON object"}, status=400)
        try:
            answer = await core.handle(body)
        except RequestRejected as rejection:
            return web.json_response(
                {"error": _REJECTION_TEXT[rejection.reason]},
                status=_REJECTION_STATUS[rejection.reason],
            )
        return web.json_response(answer)

    async def healthz(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app = web.Application(client_max_size=config.max_body_bytes)
    app.router.add_post("/v1/invoke", invoke)
    app.router.add_get("/healthz", healthz)
    return app
