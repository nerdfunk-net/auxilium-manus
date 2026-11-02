"""httpx transport for Nautobot's GraphQL API (read-only use).

Paging and list helpers come from ``nautobot_read.client.GraphQLClient``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from types import TracebackType
from typing import Any

import httpx
from nautobot_read.client import GraphQLClient, NautobotError

from nautobot_mcp.config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_ERROR_CHARS = 500
_STATUS_HINTS = {
    401: "Nautobot rejected the API token (HTTP 401). Check NAUTOBOT_TOKEN.",
    403: "The API token lacks permission for this request (HTTP 403).",
}


class NautobotClient(GraphQLClient):
    def __init__(self, config: Config) -> None:
        self._http = httpx.AsyncClient(
            base_url=config.url,
            headers={"Authorization": f"Token {config.token}", "Accept": "application/json"},
            verify=config.verify_ssl,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    async def __aenter__(self) -> NautobotClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a query and return its ``data``; raise ``NautobotError`` on any failure."""
        response = await self._send(
            self._http.post("/api/graphql/", json={"query": query, "variables": variables or {}})
        )
        payload = _json_or_none(response)
        if response.status_code in _STATUS_HINTS:
            raise NautobotError(_STATUS_HINTS[response.status_code])
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            # Nautobot's wording (schema hints, choice lists) is for the operator's log, not for
            # the model: the names were validated before the query, so this is not the model's
            # to fix.
            logger.warning("Nautobot rejected a query: %s", _summarize(errors))
            raise NautobotError("Nautobot rejected the query.")
        if response.status_code >= 400:
            raise NautobotError(f"Nautobot returned an error (HTTP {response.status_code}).")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise NautobotError("Nautobot sent an unexpected response.")
        return payload["data"]


    async def rest_get(self, endpoint: str) -> Any:
        """GET ``/api/<endpoint>`` (a path and query built by the library from constants and
        URL-encoded values) and return the JSON body. Used for list counts only."""
        response = await self._send(self._http.get(f"/api/{endpoint.lstrip('/')}"))
        if response.status_code in _STATUS_HINTS:
            raise NautobotError(_STATUS_HINTS[response.status_code])
        if response.status_code >= 400:
            raise NautobotError(f"Nautobot returned an error (HTTP {response.status_code}).")
        payload = _json_or_none(response)
        if payload is None:
            raise NautobotError("Nautobot sent an unexpected response.")
        return payload

    @staticmethod
    async def _send(request: Awaitable[httpx.Response]) -> httpx.Response:
        try:
            return await request
        except httpx.HTTPError as exc:
            logger.warning("Nautobot request failed: %s", type(exc).__name__)
            raise NautobotError("Could not reach Nautobot. Check that it is running.") from exc


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _summarize(errors: Any) -> str:
    messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
    return "; ".join(messages)[:MAX_ERROR_CHARS]
