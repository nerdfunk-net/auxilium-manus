"""Helpers shared by every query: paging bounds and the response envelope."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from nautobot_read.client import Page
from nautobot_read.networks import InvalidInputError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# Far beyond any real list, and inside GraphQL's 32-bit Int.
MAX_OFFSET = 100_000

# Object types that have roles, statuses or tags in Nautobot, as ``app.model``.
ContentType = Literal["dcim.device", "dcim.location", "ipam.ipaddress", "ipam.prefix"]


def check_paging(limit: int, offset: int) -> None:
    """Reject paging values outside the bounds the tools advertise."""
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}, not {limit}.")
    if not 0 <= offset <= MAX_OFFSET:
        raise InvalidInputError(f"offset must be between 0 and {MAX_OFFSET}, not {offset}.")


def envelope(
    items: Sequence[dict[str, Any]],
    page: Page | None,
    *,
    offset: int,
    applied_filters: dict[str, Any],
) -> dict[str, Any]:
    """The common list response: rows, paging state and how the request was interpreted."""
    return {
        "items": list(items),
        "returned": len(items),
        "has_more": bool(page and page.has_more),
        "offset": offset,
        "applied_filters": applied_filters,
    }


def names(rows: Sequence[dict[str, Any]] | None) -> list[str]:
    """``[{"name": "a"}, ...]`` to ``["a", ...]`` (GraphQL nested name objects)."""
    return [row["name"] for row in rows or []]
