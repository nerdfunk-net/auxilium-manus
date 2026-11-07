"""All IP prefixes of a Nautobot (read-only, GraphQL, paged).

Used to compare Nautobot with another source of subnets. A response with GraphQL ``errors`` or
without the prefix list is an error, never "no prefixes": a partial answer must not be read as a
Nautobot that lacks the subnets.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Protocol

from services.nautobot.common.exceptions import NautobotAPIError

PAGE_SIZE = 1000
# More prefixes than this fail instead of being truncated.
MAX_PREFIXES = 200_000

_QUERY = (
    "query($limit: Int, $offset: Int) { "
    "prefixes(limit: $limit, offset: $offset) { prefix type status { name } namespace { name } } }"
)


class NautobotGraphQLClient(Protocol):
    async def graphql_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NautobotPrefix:
    prefix: str  # the network form, for example 10.1.1.0/24
    namespace: str | None
    status: str | None
    type: str | None


class NautobotPrefixReader:
    def __init__(self, client: NautobotGraphQLClient, *, max_prefixes: int = MAX_PREFIXES) -> None:
        self._client = client
        self._max = max_prefixes

    async def list_prefixes(self) -> tuple[NautobotPrefix, ...]:
        prefixes: list[NautobotPrefix] = []
        offset = 0
        while True:
            rows = _page(
                await self._client.graphql_query(_QUERY, {"limit": PAGE_SIZE, "offset": offset})
            )
            for row in rows:
                if (item := _prefix(row)) is not None:
                    prefixes.append(item)
            if len(prefixes) > self._max:
                raise NautobotAPIError(
                    f"Nautobot has more than {self._max} prefixes", code="too_many_objects"
                )
            if len(rows) < PAGE_SIZE:
                return tuple(prefixes)
            offset += PAGE_SIZE


def _page(body: Any) -> list[Any]:
    if isinstance(body, dict) and body.get("errors"):
        raise NautobotAPIError(
            "Nautobot's GraphQL API reported an error for the prefix query", code="graphql_error"
        )
    data = body.get("data") if isinstance(body, dict) else None
    rows = data.get("prefixes") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise NautobotAPIError(
            "Nautobot answered the prefix query without a prefix list", code="invalid_response"
        )
    return rows


def _name(value: Any) -> str | None:
    name = value.get("name") if isinstance(value, dict) else None
    return name if isinstance(name, str) and name else None


def _prefix(row: Any) -> NautobotPrefix | None:
    if not isinstance(row, dict) or not isinstance(row.get("prefix"), str):
        return None
    try:
        network = ipaddress.ip_network(row["prefix"], strict=False)
    except ValueError:
        return None
    kind = row.get("type")
    return NautobotPrefix(
        prefix=str(network),
        namespace=_name(row.get("namespace")),
        status=_name(row.get("status")),
        type=kind if isinstance(kind, str) else None,
    )
