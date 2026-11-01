"""Tools that read stored results by handle: ``query_result`` and ``fetch_slice``.

Pure reads (doc/AI_TOOL_CHAIN.md §6.1, §12.2). A tool that produces a big result stores it in the
``ResultStore`` and returns a preview plus a handle; these two tools are how the model gets at the
rest without the whole result entering the prompt.

Rules enforced here (and tested without a model):

* the handle is looked up under the calling user's id, so another user's handle looks expired;
* the data class the result was stored under is checked against the user's opt-in on *every*
  read, so switching the opt-in off withholds old handles at once;
* every output is bounded: at most ``PREVIEW_ROWS`` rows or ``MAX_SLICE_CHARS`` characters;
* values are redacted as data *before* they are JSON-encoded (text goes outside the JSON, as
  ``get_artifact`` does), because JSON turns newlines into ``\\n`` and the line-anchored secret
  patterns stop matching;
* the model supplies a field name, an operator from a closed set and a value, never code.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.ai_assistant.data_sharing import not_shared_marker
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import (
    PREVIEW_ROWS,
    ResultEnvelope,
    envelope_output,
    redact_envelope,
)

# Key of the ``ResultStore`` in ``ToolContext.extras``; the surface builder puts it there.
RESULT_STORE_KEY = "result_store"
MAX_SLICE_CHARS = 4000
MAX_FILTERS = 5
MAX_FIELDS = 20

_HANDLE_FIELD = Field(
    min_length=1,
    max_length=64,
    description="Handle of a stored result, for example 'res_8f3a1c0d2b4e'",
)
_EXPIRED = (
    "Unknown or expired handle. Stored results expire after a few hours and belong to one user; "
    "run the tool that produced it again."
)

_NUMERIC = re.compile(r"[-+]?\d+(\.\d+)?")

Operator = Literal["eq", "ne", "contains", "startswith", "gt", "ge", "lt", "le"]


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        min_length=1,
        max_length=100,
        description="Column name; use a dot for nested values, e.g. 'Interface.name'",
    )
    op: Operator = Field(
        description="eq/ne compare as equal text or number; contains also tests list members"
    )
    value: Annotated[str | int | float | bool, Field(description="Value to compare with")]

    @model_validator(mode="after")
    def _text_ops_need_text(self) -> Filter:
        # "" is contained in every string and starts every string: that is never what was meant.
        if self.op in ("contains", "startswith") and str(self.value) == "":
            raise ValueError(f"{self.op} needs a non-empty value")
        return self


class QueryResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = _HANDLE_FIELD
    filters: list[Filter] = Field(
        default_factory=list, max_length=MAX_FILTERS, description="All filters must match (AND)"
    )
    fields: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        max_length=MAX_FIELDS,
        description="Columns to return (dot paths allowed); empty means all columns",
    )
    limit: int = Field(default=PREVIEW_ROWS, ge=1, le=PREVIEW_ROWS, description="Rows to return")
    offset: int = Field(
        default=0, ge=0, le=1_000_000, description="Skip this many matching rows (to page)"
    )


class FetchSliceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = _HANDLE_FIELD
    offset: int = Field(
        default=0, ge=0, le=10_000_000, description="First row (table) or character (text)"
    )
    limit: int = Field(
        default=PREVIEW_ROWS,
        ge=1,
        le=MAX_SLICE_CHARS,
        description=(
            f"Rows (max {PREVIEW_ROWS}) for a table, characters (max {MAX_SLICE_CHARS}) for text"
        ),
    )


# -- helpers ----------------------------------------------------------------------------------


def _store(ctx: ToolContext) -> ResultStore:
    return ctx.extras[RESULT_STORE_KEY]


async def _load(ctx: ToolContext, handle: str) -> StoredResult | ToolOutput:
    """The stored result, or a ready-made ToolOutput saying why it cannot be used."""
    try:
        stored = await _store(ctx).get(ctx.user_id, handle)
    except ResultStoreUnavailableError:
        return ToolOutput(
            "The result store is unavailable right now; stored results cannot be read. "
            "Run the original tool again.",
            is_error=True,
        )
    if stored is None:
        return ToolOutput(_EXPIRED, is_error=True)
    ctx.audit_refs.add(f"result:{handle}")
    if not ctx.sharing.allows(stored.data_class):
        return ToolOutput(json.dumps(not_shared_marker(stored.data_class)))
    return stored


def _get_path(row: dict[str, Any], path: str) -> tuple[bool, Any]:
    node: Any = row
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _number(value: Any) -> float | None:
    """A real number, or text that is one ('42'); never a bool, never None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and _NUMERIC.fullmatch(value.strip()):
        return float(value)
    return None


def _text(value: Any) -> str | None:
    """Text a substring test may look at: strings and numbers only (not None, bool, dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _equal(cell: Any, value: Any) -> bool:
    if cell is None:
        return False
    if isinstance(cell, bool) or isinstance(value, bool):
        # True is not 1. A bool may be given as the text 'true' / 'false'.
        as_bool = {"true": True, "false": False}
        cell_b = cell if isinstance(cell, bool) else as_bool.get(str(cell).casefold())
        value_b = value if isinstance(value, bool) else as_bool.get(str(value).casefold())
        return cell_b is not None and cell_b == value_b
    if _is_real_number(cell) or _is_real_number(value):
        cell_n, value_n = _number(cell), _number(value)
        return cell_n is not None and value_n is not None and cell_n == value_n
    return isinstance(cell, str) and isinstance(value, str) and cell == value


def _is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _compare(cell: Any, value: Any, op: str) -> bool:
    cell_n, value_n = _number(cell), _number(value)
    if cell_n is None or value_n is None:
        return False
    return {
        "gt": cell_n > value_n,
        "ge": cell_n >= value_n,
        "lt": cell_n < value_n,
        "le": cell_n <= value_n,
    }[op]


def _matches(row: dict[str, Any], flt: Filter) -> bool:
    found, cell = _get_path(row, flt.field)
    if not found:
        return False
    match flt.op:
        case "eq":
            return _equal(cell, flt.value)
        case "ne":
            return not _equal(cell, flt.value)
        case "contains":
            if isinstance(cell, list):
                return any(_equal(item, flt.value) for item in cell)
            text = _text(cell)
            return text is not None and str(flt.value) in text
        case "startswith":
            text = _text(cell)
            return text is not None and text.startswith(str(flt.value))
        case _:
            return _compare(cell, flt.value, flt.op)


def _project(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    if not fields:
        return row
    projected: dict[str, Any] = {}
    for path in fields:
        found, value = _get_path(row, path)
        if found:
            projected[path] = value
    return projected


async def _page_output(
    ctx: ToolContext,
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int,
    total: int,
    kind: str,
) -> ToolOutput:
    """One window of rows as a redacted envelope. ``truncated`` means 'more rows follow'."""
    window = rows[:limit]
    envelope = ResultEnvelope(rows=window, total_rows=total, truncated=offset + len(window) < total)
    envelope = await asyncio.to_thread(redact_envelope, envelope, ctx.redactor)
    return envelope_output(envelope, extra={"offset": offset, "handle_kind": kind})


# -- text windows -----------------------------------------------------------------------------

_BEGIN = "-----BEGIN"
_END = "-----END"
# How far a private-key block may reach before or after a window and still be pulled in whole.
_KEY_REACH = 8000


def _text_window(text: str, offset: int, limit: int) -> tuple[int, int]:
    """The (start, end) of the slice to show.

    The end falls on a line boundary when there is one in the window's second half. A
    private-key block is never split: a window starting inside one moves back to its BEGIN line, a
    window ending inside one runs on to its END line, so the redactor always sees the whole block.
    """
    start = min(offset, len(text))
    begin = text.rfind(_BEGIN, 0, start)
    if begin != -1 and start - begin <= _KEY_REACH and text.find(_END, begin, start) == -1:
        start = text.rfind("\n", 0, begin) + 1
    end = min(offset + limit, len(text))
    if end < len(text):
        cut = text.rfind("\n", start, end)
        if cut > start + (end - start) // 2:
            end = cut + 1
    key = text.rfind(_BEGIN, start, end)
    if key != -1 and text.find(_END, key, end) == -1:
        stop = text.find(_END, end)
        if stop != -1 and stop - end <= _KEY_REACH:
            newline = text.find("\n", stop)
            end = len(text) if newline == -1 else newline + 1
        else:
            end = max(start, text.rfind("\n", start, key) + 1)
    return start, end


# -- handlers ---------------------------------------------------------------------------------


async def _query_result(ctx: ToolContext, args: QueryResultInput) -> ToolOutput:
    loaded = await _load(ctx, args.handle)
    if isinstance(loaded, ToolOutput):
        return loaded
    if loaded.rows is None:
        return ToolOutput(
            "This handle holds text, not a table. Use fetch_slice to read it.", is_error=True
        )
    matching = [r for r in loaded.rows if all(_matches(r, f) for f in args.filters)]
    window = [_project(r, args.fields) for r in matching[args.offset : args.offset + args.limit]]
    return await _page_output(
        ctx, window, offset=args.offset, limit=args.limit, total=len(matching), kind=loaded.kind
    )


async def _fetch_slice(ctx: ToolContext, args: FetchSliceInput) -> ToolOutput:
    loaded = await _load(ctx, args.handle)
    if isinstance(loaded, ToolOutput):
        return loaded
    if loaded.rows is not None:
        if args.limit > PREVIEW_ROWS:
            return ToolOutput(f"limit for a table is at most {PREVIEW_ROWS} rows", is_error=True)
        window = loaded.rows[args.offset : args.offset + args.limit]
        return await _page_output(
            ctx,
            window,
            offset=args.offset,
            limit=args.limit,
            total=len(loaded.rows),
            kind=loaded.kind,
        )
    text = loaded.text or ""
    start, end = _text_window(text, args.offset, args.limit)
    # Redact the raw text (real newlines), then wrap it. The tags keep it out of the JSON header,
    # exactly like get_artifact.
    body = await asyncio.to_thread(ctx.redactor.redact, text[start:end])
    more = end < len(text)
    header = {
        "offset": start,
        "next_offset": end if more else None,
        "total_chars": len(text),
        "truncated": more,
        "handle_kind": loaded.kind,
    }
    return ToolOutput(f"{json.dumps(header)}\n<text>\n{body}\n</text>", truncated=more)


# -- registration -----------------------------------------------------------------------------

_DESCRIPTIONS = {
    "query_result": (
        "Filter and project a stored table result by its handle. Use it when a tool returned "
        "'truncated': true with a handle. Returns at most 20 rows plus the total that matched. "
        "Filters are ANDed; fields picks columns; page the matches with offset."
    ),
    "fetch_slice": (
        "Read the next part of a stored result by handle: rows for a table, characters for a "
        "text such as a configuration. Page with offset (text: use next_offset). It pages the "
        "whole stored result and ignores filters; use query_result to filter."
    ),
}


def build_result_tools() -> list[Tool]:
    handlers: dict[str, tuple[type[BaseModel], Callable[..., Any]]] = {
        "query_result": (QueryResultInput, _query_result),
        "fetch_slice": (FetchSliceInput, _fetch_slice),
    }
    return [
        Tool(name=name, description=_DESCRIPTIONS[name], input_model=model, handler=handler)
        for name, (model, handler) in handlers.items()
    ]
