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
from urllib.parse import urlencode

DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_ITEMS = 5000
COUNT_FALLBACK_CAP = 5000
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# GraphQL root -> REST list endpoint, for the roots whose REST filters are known to match the
# GraphQL ones (both come from Nautobot's FilterSets). A root missing here is counted by paging
# GraphQL instead; remove a root from this map if its REST count ever differs from its list.
REST_LIST_ENDPOINTS = {
    "devices": "dcim/devices",
    "interfaces": "dcim/interfaces",
    "locations": "dcim/locations",
    "ip_addresses": "ipam/ip-addresses",
    "prefixes": "ipam/prefixes",
    "virtual_chassis": "dcim/virtual-chassis",
}


class NautobotError(RuntimeError):
    """A Nautobot call failed; the message is short and safe to show to the LLM."""


class TooManyRowsError(NautobotError):
    """A list is too long to collect whole (``list_all``); a caller that can do without the
    full list falls back, any other caller shows the message."""


class RestNotSupported(NautobotError):
    """The client has no REST transport (callers that can do without fall back to GraphQL)."""


@dataclass(frozen=True)
class Count:
    """How many rows match a filter; ``exact`` is false when counting stopped at the cap."""

    total: int
    exact: bool


@dataclass(frozen=True)
class Page:
    """One page of a list query; ``has_more`` is true when rows remain after it."""

    items: tuple[dict[str, Any], ...]
    has_more: bool


# A filter value: a list of strings (most filters), or a bool for a boolean filter such as
# ``has_cable`` (Nautobot's GraphQL declares those as ``Boolean``, not a list of strings).
Filters = Mapping[str, Sequence[str] | bool | None]


def _active_filters(filters: Filters) -> dict[str, list[str] | bool]:
    """The filters that carry a value: non-empty lists, and both ``True`` and ``False``."""
    active: dict[str, list[str] | bool] = {}
    for name, value in filters.items():
        if isinstance(value, bool):
            active[name] = value
        elif value:
            active[name] = list(value)
    return active


def _variable_type(value: list[str] | bool) -> str:
    return "Boolean" if isinstance(value, bool) else "[String]"


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
        raise RestNotSupported("This Nautobot client cannot call the REST API.")

    async def list_page(
        self,
        root: str,
        selection: str,
        filters: Filters,
        *,
        limit: int,
        offset: int,
    ) -> Page:
        """Fetch ``limit`` rows (one extra is requested to learn whether more exist).

        ``root``, ``selection`` and the filter names are code constants from the tool
        whitelist, never LLM input; they are still checked to be plain identifiers. Filter
        values travel as GraphQL variables, never inside the query text.
        """
        active = _active_filters(filters)
        for name in (root, *active):
            if not _IDENTIFIER.match(name):
                raise ValueError(f"not a plain identifier: {name!r}")
        declarations = [
            "$limit: Int",
            "$offset: Int",
            *(f"$f_{n}: {_variable_type(v)}" for n, v in active.items()),
        ]
        arguments = ["limit: $limit", "offset: $offset", *(f"{n}: $f_{n}" for n in active)]
        query = (
            f"query({', '.join(declarations)}) "
            f"{{ {root}({', '.join(arguments)}) {{ {selection} }} }}"
        )
        variables: dict[str, Any] = {"limit": limit + 1, "offset": offset}
        variables.update({f"f_{name}": values for name, values in active.items()})
        rows = (await self.graphql(query, variables)).get(root) or []
        return Page(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def count(self, root: str, filters: Filters) -> Count:
        """How many rows of ``root`` match ``filters``.

        One REST request (``?limit=1`` and read ``count``) when the root has an endpoint in
        ``REST_LIST_ENDPOINTS`` and the client can do REST; otherwise GraphQL pages of ``id`` up
        to ``COUNT_FALLBACK_CAP`` rows, after which the count is a lower bound. Root and filter
        names are code constants (checked to be plain identifiers); values are URL-encoded.

        The REST request carries ``brief=true`` so the one row Nautobot sends back is its short
        form (no comments or custom fields; only ``count`` is read). A 200 without a usable
        count (``count: null`` after Nautobot's count timeout) is not an error: the capped
        GraphQL count answers instead. Anything else that is not a count is.
        """
        active = _active_filters(filters)
        for name in (root, *active):
            if not _IDENTIFIER.match(name):
                raise ValueError(f"not a plain identifier: {name!r}")
        endpoint = REST_LIST_ENDPOINTS.get(root)
        if endpoint is not None:
            pairs = [
                (name, value)
                for name, values in active.items()
                for value in ([str(values).lower()] if isinstance(values, bool) else values)
            ]
            try:
                query = urlencode([*pairs, ("limit", 1), ("brief", "true")])
                data = await self.rest_get(f"{endpoint}/?{query}")
            except RestNotSupported:
                pass
            else:
                if not isinstance(data, dict):
                    raise NautobotError("Nautobot sent an unexpected response.")
                total = data.get("count")
                if total is not None:
                    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                        raise NautobotError("Nautobot sent an unexpected response.")
                    return Count(total, exact=True)
        return await self._count_by_paging(root, active)

    async def _count_by_paging(self, root: str, filters: Filters) -> Count:
        counted = 0
        while True:
            page = await self.list_page(
                root, "id", filters, limit=DEFAULT_PAGE_SIZE, offset=counted
            )
            counted += len(page.items)
            if not page.has_more:
                return Count(counted, exact=True)
            if counted >= COUNT_FALLBACK_CAP:
                return Count(COUNT_FALLBACK_CAP, exact=False)

    async def list_all(
        self,
        root: str,
        selection: str,
        filters: Filters | None = None,
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
