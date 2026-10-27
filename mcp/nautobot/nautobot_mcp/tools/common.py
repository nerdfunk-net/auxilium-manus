"""Helpers shared by every tool: error mapping, paging bounds and the response envelope."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from nautobot_mcp.client import NautobotError, Page
from nautobot_mcp.networks import InvalidInputError
from nautobot_mcp.vocabularies import AmbiguousNameError
from nautobot_mcp.vocabulary import UnknownNameError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

# Object types that have roles, statuses or tags in Nautobot, as ``app.model``.
ContentType = Literal["dcim.device", "dcim.location", "ipam.ipaddress", "ipam.prefix"]

Limit = Annotated[
    int, Field(ge=1, le=MAX_LIMIT, description=f"Rows per page (1-{MAX_LIMIT}, default 50).")
]
Offset = Annotated[int, Field(ge=0, description="Rows to skip; use with has_more to page.")]

def guarded[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn our expected errors into ``ToolError`` so the model reads the real message.

    The SDK shows the model only ``ToolError`` text; any other exception becomes a bare
    "Error executing tool". ``functools.wraps`` keeps the signature for schema generation.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except (UnknownNameError, AmbiguousNameError, InvalidInputError, NautobotError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


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
