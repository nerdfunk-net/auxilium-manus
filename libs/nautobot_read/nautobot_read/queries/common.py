"""Helpers shared by every query: paging bounds and the response envelope."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from nautobot_read.client import NautobotError, Page
from nautobot_read.context import QueryContext
from nautobot_read.networks import InvalidInputError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# Far beyond any real list, and inside GraphQL's 32-bit Int.
MAX_OFFSET = 100_000

# Object types that have roles, statuses or tags in Nautobot, as ``app.model``.
ContentType = Literal["dcim.device", "dcim.location", "ipam.ipaddress", "ipam.prefix"]


CONTRADICTION = "Nautobot's count disagrees with the list, so no total is given."


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


async def list_with_total(
    ctx: QueryContext,
    root: str,
    selection: str,
    filters: Mapping[str, Sequence[str] | None],
    *,
    limit: int,
    offset: int,
    to_item: Callable[[dict[str, Any]], dict[str, Any]],
    applied: dict[str, Any],
) -> dict[str, Any]:
    """One page of ``root`` plus how many rows match in all, so "how many" needs one call.

    ``total`` is free when the page is the last one (``offset + returned``). Otherwise one count
    request is made. A failing count must not hide rows already fetched: the page is returned
    with ``total_error`` (a short message written for the model) instead of ``total``.
    ``total_exact`` is false when counting stopped at its cap, so ``total`` is a lower bound.

    The count and the page are different requests; a count that cannot be true of the page
    just fetched (fewer rows than the page proves exist) is a filter that was not applied the
    same way, so it is reported as ``total_error`` and never shown as an exact total. A count
    that is too *large* cannot be detected here: that needs the live comparison in
    ``doc/AI_TOOL_CHAIN.md`` §31.
    """
    page = await ctx.client.list_page(root, selection, filters, limit=limit, offset=offset)
    items = [to_item(row) for row in page.items]
    result = envelope(items, page, offset=offset, applied_filters=applied)
    # An empty last page past the end says nothing about the total: count it.
    if not page.has_more and (items or offset == 0):
        return {**result, "total": offset + len(items), "total_exact": True}
    try:
        count = await ctx.client.count(root, filters)
    except NautobotError as exc:
        return {**result, "total_error": str(exc)}
    proven = offset + len(items) + 1  # has_more: at least one row beyond this page
    if page.has_more and count.total < proven:
        if count.exact:
            return {**result, "total_error": CONTRADICTION}
        return {**result, "total": proven, "total_exact": False}
    return {**result, "total": count.total, "total_exact": count.exact}
