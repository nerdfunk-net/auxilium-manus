"""Small async GraphQL client for Nautobot (read-only use)."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from nautobot_mcp.config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_ITEMS = 5000
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ERROR_CHARS = 500
_STATUS_HINTS = {
    401: "Nautobot rejected the API token (HTTP 401). Check NAUTOBOT_TOKEN.",
    403: "The API token lacks permission for this request (HTTP 403).",
}


class NautobotError(RuntimeError):
    """A Nautobot call failed; the message is short and safe to show to the LLM."""


@dataclass(frozen=True)
class Page:
    """One page of a list query; ``has_more`` is true when rows remain after it."""

    items: tuple[dict[str, Any], ...]
    has_more: bool


class NautobotClient:
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
        try:
            response = await self._http.post(
                "/api/graphql/", json={"query": query, "variables": variables or {}}
            )
        except httpx.HTTPError as exc:
            logger.warning("Nautobot request failed: %s", type(exc).__name__)
            raise NautobotError("Could not reach Nautobot. Check that it is running.") from exc

        payload = _json_or_none(response)
        if response.status_code in _STATUS_HINTS:
            raise NautobotError(_STATUS_HINTS[response.status_code])
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            raise NautobotError(_summarize(errors))
        if response.status_code >= 400:
            raise NautobotError(f"Nautobot returned an error (HTTP {response.status_code}).")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise NautobotError("Nautobot sent an unexpected response.")
        return payload["data"]

    async def list_page(
        self,
        root: str,
        selection: str,
        filters: Mapping[str, Sequence[str] | None],
        *,
        limit: int,
        offset: int,
    ) -> Page:
        """Fetch ``limit`` rows (one extra is requested to learn whether more exist).

        ``root``, ``selection`` and the filter names are code constants from the tool
        whitelist, never LLM input; they are still checked to be plain identifiers. Filter
        values travel as GraphQL variables, never inside the query text.
        """
        active = {name: list(values) for name, values in filters.items() if values}
        for name in (root, *active):
            if not _IDENTIFIER.match(name):
                raise ValueError(f"not a plain identifier: {name!r}")
        declarations = ["$limit: Int", "$offset: Int", *(f"$f_{n}: [String]" for n in active)]
        arguments = ["limit: $limit", "offset: $offset", *(f"{n}: $f_{n}" for n in active)]
        query = (
            f"query({', '.join(declarations)}) "
            f"{{ {root}({', '.join(arguments)}) {{ {selection} }} }}"
        )
        variables: dict[str, Any] = {"limit": limit + 1, "offset": offset}
        variables.update({f"f_{name}": values for name, values in active.items()})
        rows = (await self.graphql(query, variables)).get(root) or []
        return Page(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def list_all(
        self,
        root: str,
        selection: str,
        filters: Mapping[str, Sequence[str] | None] | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> list[dict[str, Any]]:
        """Collect pages until exhausted or ``max_items`` rows (used for vocabularies)."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while len(rows) < max_items:
            page = await self.list_page(
                root, selection, filters or {}, limit=page_size, offset=offset
            )
            rows.extend(page.items)
            if not page.has_more:
                break
            offset += page_size
        return rows[:max_items]


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _summarize(errors: Any) -> str:
    messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
    return "; ".join(messages)[:MAX_ERROR_CHARS]
