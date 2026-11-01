"""Helpers shared by every MCP tool: error mapping and the typed paging parameters."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from nautobot_read.errors import EXPECTED_ERRORS
from nautobot_read.queries.common import MAX_LIMIT, MAX_OFFSET, ContentType
from pydantic import Field

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

__all__ = ["READ_ONLY", "ContentType", "Limit", "Offset", "guarded"]

Limit = Annotated[
    int, Field(ge=1, le=MAX_LIMIT, description=f"Rows per page (1-{MAX_LIMIT}, default 50).")
]
Offset = Annotated[
    int,
    Field(ge=0, le=MAX_OFFSET, description="Rows to skip; use with has_more to page."),
]


def guarded[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn our expected errors into ``ToolError`` so the model reads the real message.

    The SDK shows the model only ``ToolError`` text; any other exception becomes a bare
    "Error executing tool". ``functools.wraps`` keeps the signature for schema generation.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except EXPECTED_ERRORS as exc:
            raise ToolError(str(exc)) from exc

    return wrapper
