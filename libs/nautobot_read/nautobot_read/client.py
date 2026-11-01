"""Paging over Nautobot's GraphQL API, independent of how a request is sent.

A concrete client (the MCP server's httpx client, the backend's ``NautobotService`` adapter)
subclasses ``GraphQLClient`` and implements only ``graphql``. Listing, paging and the
"collect everything" helper for vocabularies are shared.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_ITEMS = 5000
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NautobotError(RuntimeError):
    """A Nautobot call failed; the message is short and safe to show to the LLM."""


class TooManyRowsError(NautobotError):
    """A list is too long to collect whole (``list_all``); a caller that can do without the
    full list falls back, any other caller shows the message."""


@dataclass(frozen=True)
class Page:
    """One page of a list query; ``has_more`` is true when rows remain after it."""

    items: tuple[dict[str, Any], ...]
    has_more: bool


class GraphQLClient(ABC):
    """Read-only list helpers on top of a single ``graphql`` transport method."""

    @abstractmethod
    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a query and return its ``data``; raise ``NautobotError`` on any failure."""

    async def rest_get(self, endpoint: str) -> Any:
        """GET a REST path below ``/api/`` (for the few reads GraphQL cannot do).

        Only for clients that can; the default says so. ``endpoint`` is built by a query from
        constants and validated ids, never from model text.
        """
        raise NautobotError("This Nautobot client cannot call the REST API.")

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
        """Collect every page (used for vocabularies).

        Raises ``NautobotError`` when more than ``max_items`` rows exist. Truncating silently
        would drop names from a vocabulary, and a lookup of a dropped name then fails with a
        misleading "No location '...'".
        """
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.list_page(
                root, selection, filters or {}, limit=page_size, offset=offset
            )
            rows.extend(page.items)
            if len(rows) > max_items or (page.has_more and len(rows) >= max_items):
                raise TooManyRowsError(
                    f"Nautobot has more than {max_items} {root}; too many to load as a list."
                )
            if not page.has_more:
                return rows
            offset += page_size
