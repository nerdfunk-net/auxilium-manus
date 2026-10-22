"""HTTP transport: ``POST {url}/v1/invoke`` with the sealed envelope as the JSON body.

The bearer token is derived from the shared secret and only lets the agent drop unauthenticated
traffic cheaply; the envelope is what protects the content. Plain http is acceptable inside a
Docker network because the payload is encrypted.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from services.agents.envelope import derive_http_token
from services.agents.exceptions import (
    AgentAuthError,
    AgentOfflineError,
    AgentTimeoutError,
    AgentTransportError,
)

INVOKE_PATH = "/v1/invoke"
MAX_RESPONSE_BYTES = 16 * 1_048_576


class HttpTransport:
    def __init__(
        self,
        *,
        url: str,
        agent_id: str,
        secret: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = url.rstrip("/") + INVOKE_PATH
        self._token = derive_http_token(secret, agent_id)
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._max_response_bytes = MAX_RESPONSE_BYTES

    async def call(self, envelope: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                json=envelope,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(timeout),
            ) as response:
                body = await self._read_limited(response)
                status_code = response.status_code
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise AgentOfflineError("agent is not reachable") from exc
        except httpx.TimeoutException as exc:
            raise AgentTimeoutError("agent did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise AgentTransportError("HTTP request to the agent failed") from exc

        if status_code in (401, 403):
            raise AgentAuthError("agent rejected the bearer token")
        if status_code != 200:
            raise AgentTransportError(f"agent answered HTTP {status_code}")
        try:
            decoded = json.loads(body)
        except ValueError as exc:
            raise AgentTransportError("agent answered with invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise AgentTransportError("agent answered with an unexpected JSON shape")
        return decoded

    async def _read_limited(self, response: httpx.Response) -> bytes:
        received = bytearray()
        async for chunk in response.aiter_bytes():
            received.extend(chunk)
            if len(received) > self._max_response_bytes:
                raise AgentTransportError("agent response is too large")
        return bytes(received)

    async def aclose(self) -> None:
        await self._client.aclose()
