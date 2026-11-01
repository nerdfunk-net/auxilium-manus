"""``diff_results``: compare two stored tables (doc/AI_TOOL_CHAIN.md §12.3).

A pure read, like ``query_result``: both handles are looked up under the calling user, the data
class of each is checked against the opt-in, and the difference is published as the standard
envelope (preview plus a handle of its own). The comparison itself is ``result_diff.diff_tables``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.result_diff import DiffError, diff_tables
from services.ai_assistant.tools.result_publish import publish_table
from services.ai_assistant.tools.result_tools import HANDLE_FIELD, load_stored_result

MAX_KEY_COLUMNS = 5
MAX_IGNORED_FIELDS = 20

# Strictest first: a diff holds rows of both tables, so it takes the stricter class of the two.
_STRICTNESS = (
    DataClass.CONTENT,
    DataClass.REPORT_DATA,
    DataClass.CONFIG_CONTEXT,
    DataClass.CUSTOM_FIELDS,
    DataClass.ADDRESSES,
    DataClass.INVENTORY,
)

_ColumnName = Annotated[str, Field(min_length=1, max_length=100)]


class DiffResultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle_a: str = HANDLE_FIELD
    handle_b: str = HANDLE_FIELD
    key: list[_ColumnName] = Field(
        default_factory=list,
        max_length=MAX_KEY_COLUMNS,
        description=(
            "Columns that identify a row (dot paths allowed), e.g. ['Node', 'Network']. With a "
            "key, matching rows are compared field by field; without one, whole rows are compared"
        ),
    )
    ignore_fields: list[_ColumnName] = Field(
        default_factory=list,
        max_length=MAX_IGNORED_FIELDS,
        description="Top-level columns to leave out of the comparison (timestamps, counters)",
    )


def _stricter(a: DataClass, b: DataClass) -> DataClass:
    return min((a, b), key=_STRICTNESS.index)


async def _diff_results(ctx: ToolContext, args: DiffResultsInput) -> ToolOutput:
    first = await load_stored_result(ctx, args.handle_a)
    if isinstance(first, ToolOutput):
        return first
    second = await load_stored_result(ctx, args.handle_b)
    if isinstance(second, ToolOutput):
        return second
    if first.rows is None or second.rows is None:
        return ToolOutput(
            "diff_results compares two tables; one of the handles holds text.", is_error=True
        )
    try:
        result = await asyncio.to_thread(
            diff_tables,
            first.rows,
            second.rows,
            key=args.key or None,
            ignore=frozenset(args.ignore_fields),
        )
    except DiffError as exc:
        return ToolOutput(str(exc), is_error=True)
    notes = []
    if first.kind != second.kind:
        notes.append(f"The tables are of different kinds ({first.kind} and {second.kind}).")
    partial = first.partial or second.partial
    if partial:
        notes.append(
            "At least one stored table is only a prefix of the full answer (cut at a size limit), "
            "so rows reported as added or removed may only lie past the cut and the counts are "
            "not exact. Narrow both queries (nodes, prefix) until neither is cut for an exact diff."
        )
    return await publish_table(
        ctx,
        result.rows,
        kind="diff",
        data_class=_stricter(first.data_class, second.data_class),
        source_truncated=partial,
        note=" ".join(notes) or None,
        extra={
            "complete": not partial,
            "counts": result.counts,
            "compared": {"a": args.handle_a, "b": args.handle_b},
            "keyed_by": args.key or None,
        },
    )


DIFF_RESULTS_TOOL = Tool(
    name="diff_results",
    description=(
        "Compare two stored table results by handle (for example the routes of two snapshots, or "
        "the same device before and after). Give key columns that identify a row, such as "
        "['Node', 'Network'], to see which rows were removed, added or changed and which fields "
        "differ; without key whole rows are compared. ignore_fields leaves out noisy columns. "
        "Returns the counts and the differing rows (a preview and a handle when large). Both "
        "tables are the stored copies, so values the redactor hid cannot be compared."
    ),
    input_model=DiffResultsInput,
    handler=_diff_results,
)
