"""Bearer-token authentication for the HTTP transport (a plain ASGI middleware).

The SDK's ``AuthSettings`` implies an OAuth authorization server (it requires an
``issuer_url`` and advertises it), which does not fit static per-client tokens. This
middleware checks ``Authorization: Bearer <token>`` before the MCP app sees the request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

HEALTH_PATH = "/healthz"


class BearerTokenMiddleware:
    """Lets a request through only with a known token; ``GET /healthz`` is always open."""

    def __init__(self, app: ASGIApp, tokens: Mapping[str, str]) -> None:
        self._app = app
        # Compare digests, so token length never leaks and comparison is constant time.
        self._digests = tuple((name, _digest(token)) for name, token in tokens.items())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope["method"] == "GET" and scope["path"] == HEALTH_PATH:
            await _respond(send, 200, {"status": "ok"})
            return
        client = self._authenticate(scope)
        if client is None:
            peer = (scope.get("client") or ("unknown",))[0]
            logger.warning("rejected request from %s: missing or invalid bearer token", peer)
            await _respond(send, 401, {"error": "unauthorized"}, {b"www-authenticate": b"Bearer"})
            return
        logger.debug("accepted request from client '%s'", client)
        await self._app(scope, receive, send)

    def _authenticate(self, scope: Scope) -> str | None:
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        presented = _digest(token.strip())
        matched: str | None = None
        for name, digest in self._digests:  # no early exit: every candidate is compared
            if hmac.compare_digest(digest, presented):
                matched = name
        return matched


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


async def _respond(
    send: Send, status: int, body: dict[str, str], extra: dict[bytes, bytes] | None = None
) -> None:
    payload = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
    ]
    headers += list((extra or {}).items())
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
