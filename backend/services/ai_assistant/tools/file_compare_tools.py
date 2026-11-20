"""``list_file_repositories`` / ``compare_file_with_nautobot`` (doc/AI_TOOL_CHAIN.md §61).

"Compare the attribute nautobot.serial with the file compare.csv in the gitea repo": the server
reads the CSV from a git repository, reads the device values from Nautobot and finds what is on
only one side (``services/ai_assistant/file_compare_reader.py``).

**The model never sees a value.** It receives counts and a note; the two lists are stored behind a
result handle marked ``model_hidden`` (``result_tools`` refuses it) and shown to the user in a card
that fetches them with ``GET /ai/results/{handle}/compare``. So no serial number or file text
reaches the AI provider, and text in the file cannot instruct the model. For the same reason no
data-sharing switch is needed; the one exception is the list of the file's column names in a
"column not found" error, which is file content and needs the content opt-in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.audit import log_file_compare
from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.file_compare_reader import (
    CompareOutcome,
    CompareRequest,
    FileCompareError,
    FileCompareReader,
)
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY
from services.csv_lookup import MAX_MATCH_PAIRS, CsvRow, MatchedPair, Reconciliation, ValueItem

logger = logging.getLogger(__name__)

# Key of the ``FileCompareReader`` in ``ToolContext.extras``; the surface builder puts it there.
FILE_COMPARE_READER_KEY = "file_compare_reader"
COMPARE_KIND = "compare_result"
# Up to this many rows per side the card shows a list completely; above it, a sample and a download.
INLINE_ROWS_PER_SIDE = 50
MAX_FILE_COLUMNS = 20
MAX_CELL_CHARS = 200
_MAX_HALVINGS = 4
_NOTE = (
    "The lists (in the file only, in both, in Nautobot only) are shown to the user in a card "
    "with a CSV download. You were given counts only: do not guess, repeat or invent serial "
    "numbers or other values, and say that the values are in the card."
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
NautobotField = Literal["serial", "name", "primary_ip4", "location", "software_version"]
MatchMode = Literal["match", "contains"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(_Input):
    pass


class CompareFileInput(_Input):
    repository: Name | None = Field(
        None,
        description="Repository name as list_file_repositories returns it. Optional when only "
        "one repository holds CSV files.",
    )
    file: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=300, pattern=r"^[^\x00]+$"
        ),
    ] = Field(
        description="A file name such as 'compare.csv' (searched in the repository) or a path "
        "such as 'exports/compare.csv'. .csv, .tsv and .txt only."
    )
    key_column: Name = Field(description="Header of the file column to compare, e.g. 'serial'.")
    nautobot_field: NautobotField = Field(
        description="What to compare it with on the Nautobot devices: serial, name, primary_ip4 "
        "(a /mask is ignored), location (path) or software_version."
    )
    match_mode: MatchMode = Field(
        "match",
        description="'match': equal. 'contains': the Nautobot value contains the file value.",
    )
    case_insensitive: bool = Field(False, description="Ignore upper/lower case.")
    delimiter: Annotated[str, StringConstraints(max_length=5)] | None = Field(
        None, description="Column separator of the file: one character or 'tab'. Default ';'."
    )
    location: Name | None = Field(None, description="Only devices in this location (and below).")
    role: Name | None = Field(None, description="Only devices with this role. See list_roles.")
    status: Name | None = Field(None, description="Only devices with this status.")
    tag: Name | None = Field(None, description="Only devices with this tag.")
    device_type: Name | None = Field(None, description="Only this device type model.")
    platform: Name | None = Field(None, description="Only this platform.")


def _counts(result: Reconciliation) -> dict[str, int]:
    return {
        "file_rows": result.file_rows,
        "rows_without_key": result.rows_without_key,
        "devices": result.items,
        "devices_without_value": len(result.items_without_value),
        "matched_keys": result.matched_keys,
        "matched_devices": result.matched_items,
        "matched_pairs": result.match_pairs,
        "only_in_file": len(result.only_in_file),
        "only_in_nautobot": len(result.only_in_items),
        "duplicate_keys": result.duplicate_keys,
        "duplicate_device_values": result.duplicate_item_values,
        "devices_matching_several_keys": result.items_matching_several_keys,
        "short_keys": result.short_keys,
    }


def _warnings(counts: Mapping[str, int], *, contains: bool) -> list[str]:
    found: list[str] = []
    if counts["matched_pairs"] > MAX_MATCH_PAIRS:
        found.append(
            f"{counts['matched_pairs']} file row/device pairs match; the 'in both' list keeps "
            f"the first {MAX_MATCH_PAIRS}."
        )
    if counts["devices_without_value"]:
        found.append(
            f"{counts['devices_without_value']} devices have no value in this field and are not "
            "compared (listed apart in the card)."
        )
    if counts["rows_without_key"]:
        found.append(f"{counts['rows_without_key']} file rows have no key and are not compared.")
    if counts["duplicate_keys"] or counts["duplicate_device_values"]:
        found.append(
            f"duplicates: {counts['duplicate_keys']} repeated file keys and "
            f"{counts['duplicate_device_values']} repeated device values."
        )
    if contains and counts["short_keys"]:
        found.append(
            f"{counts['short_keys']} file keys have 1-2 characters; with 'contains' they match "
            "many devices, so the result may be misleading."
        )
    if contains and counts["devices_matching_several_keys"]:
        found.append(f"{counts['devices_matching_several_keys']} devices match several file keys.")
    return found


def _cell(value: str) -> str:
    return value if len(value) <= MAX_CELL_CHARS else value[: MAX_CELL_CHARS - 1] + "…"


def _file_columns(rows: Iterable[CsvRow]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for name in row.values:
            if name not in columns:
                columns.append(name)
    return columns[:MAX_FILE_COLUMNS]


def _device_row(side: str, item: ValueItem, columns: list[str]) -> dict[str, str]:
    row = {
        "side": side,
        "value": item.value or "",
        "device_name": str(item.info.get("name", "")),
        "device_location": str(item.info.get("location", "")),
        "device_id": item.id,
    }
    row.update({f"file_{name}": "" for name in columns})
    return row


def _file_row(side: str, file_row: CsvRow, columns: list[str]) -> dict[str, str]:
    row = {
        "side": side,
        "value": _cell(file_row.key),
        "device_name": "",
        "device_location": "",
        "device_id": "",
    }
    row.update({f"file_{name}": _cell(file_row.values.get(name, "")) for name in columns})
    return row


def _both_row(pair: MatchedPair, columns: list[str]) -> dict[str, str]:
    """A match: the file row's key and columns next to the device that carries the value."""
    row = _file_row("in_both", pair.row, columns)
    row["device_name"] = str(pair.item.info.get("name", ""))
    row["device_location"] = str(pair.item.info.get("location", ""))
    row["device_id"] = pair.item.id
    return row


def build_rows(result: Reconciliation) -> tuple[list[dict[str, str]], list[str]]:
    """The stored table: file-only rows, matches, Nautobot-only rows, devices without a value."""
    columns = _file_columns([*result.only_in_file, *(pair.row for pair in result.matches)])
    rows: list[dict[str, str]] = [
        _file_row("only_in_file", r, columns) for r in result.only_in_file
    ]
    rows.extend(_both_row(pair, columns) for pair in result.matches)
    rows.extend(_device_row("only_in_nautobot", item, columns) for item in result.only_in_items)
    rows.extend(_device_row("without_value", item, columns) for item in result.items_without_value)
    return rows, columns


async def _store_rows(
    store: ResultStore, user_id: int, rows: list[dict[str, str]], meta: dict[str, Any]
) -> tuple[str, bool]:
    """The handle and whether the rows were cut to fit (every side is halved together)."""
    by_side: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_side.setdefault(row["side"], []).append(row)
    keep = dict(by_side)
    for _ in range(_MAX_HALVINGS + 1):
        kept_rows = [row for side in by_side for row in keep.get(side, [])]
        cut = len(kept_rows) < len(rows)
        try:
            handle = await store.put(
                user_id,
                StoredResult(
                    kind=COMPARE_KIND,
                    data_class=DataClass.CONTENT,
                    rows=kept_rows,
                    partial=cut,
                    meta={
                        **meta,
                        "partial": cut,
                        "kept": {side: len(keep.get(side, [])) for side in by_side},
                    },
                ),
            )
        except ValueError:
            keep = {side: rows_[: len(rows_) // 2] for side, rows_ in keep.items()}
            continue
        return handle, cut
    raise ValueError("result is too large to store")


def _error_output(exc: FileCompareError, ctx: ToolContext) -> ToolOutput:
    message = str(exc)
    # The column names are file content: the model sees them only with the user's opt-in.
    if exc.columns and ctx.sharing.allows(DataClass.CONTENT):
        message = f"{message}. Columns in the file: {', '.join(exc.columns)}."
    return ToolOutput(message, is_error=True)


def _reader(ctx: ToolContext) -> FileCompareReader:
    return ctx.extras[FILE_COMPARE_READER_KEY]


async def _list_file_repositories(ctx: ToolContext, _args: NoInput) -> ToolOutput:
    try:
        repositories = await _reader(ctx).list_repositories()
    except FileCompareError as exc:
        return _error_output(exc, ctx)
    return ToolOutput(
        json.dumps(
            {
                "repositories": [
                    {
                        "name": r.name,
                        "branch": r.branch,
                        "category": r.category,
                        "last_sync": r.last_sync,
                    }
                    for r in repositories
                ]
            },
            default=str,
            indent=1,
        )
    )


def _request(args: CompareFileInput) -> CompareRequest:
    return CompareRequest(
        repository=args.repository,
        file=args.file,
        key_column=args.key_column,
        field=args.nautobot_field,
        match_mode=args.match_mode,
        case_insensitive=args.case_insensitive,
        delimiter=args.delimiter,
        filters={
            "location": args.location,
            "role": args.role,
            "status": args.status,
            "tag": args.tag,
            "device_type": args.device_type,
            "platform": args.platform,
        },
    )


async def _compare_file_with_nautobot(ctx: ToolContext, args: CompareFileInput) -> ToolOutput:
    store = ctx.extras.get(RESULT_STORE_KEY)
    if not isinstance(store, ResultStore):
        return ToolOutput(
            "The comparison cannot be shown: stored results are not available here.",
            is_error=True,
        )
    try:
        outcome = await _reader(ctx).compare(_request(args))
    except FileCompareError as exc:
        return _error_output(exc, ctx)
    return await _present(ctx, store, outcome)


async def _present(ctx: ToolContext, store: ResultStore, outcome: CompareOutcome) -> ToolOutput:
    result = outcome.reconciliation
    request = outcome.request
    counts = _counts(result)
    rows, columns = build_rows(result)
    summary = {
        "repository": outcome.repository,
        "file": outcome.file,
        "key_column": request.key_column,
        "nautobot_field": request.field,
        "match_mode": request.match_mode,
        "case_insensitive": request.case_insensitive,
        "filters": dict(outcome.applied_filters),
    }
    meta = {**summary, "model_hidden": True, "counts": counts, "columns": columns}
    try:
        handle, partial = await _store_rows(store, ctx.user_id, rows, meta)
    except ResultStoreUnavailableError:
        return ToolOutput("Stored results are unavailable right now; try again.", is_error=True)
    except ValueError:
        return ToolOutput(
            "The result is too large to show. Narrow the Nautobot side with a filter.",
            is_error=True,
        )
    warnings = _warnings(counts, contains=request.match_mode == "contains")
    if partial:
        warnings.append(
            "The lists were cut to fit the size limit of a stored result; the counts are exact."
        )
    ctx.audit_refs.add(f"result:{handle}")
    log_file_compare(
        user_id=ctx.user_id, repository=outcome.repository, file=outcome.file, counts=counts
    )
    answer = {
        **{k: v for k, v in summary.items() if k != "filters"},
        "applied_filters": dict(outcome.applied_filters),
        "counts": counts,
        "partial": partial,
        "warnings": warnings,
        "note": _NOTE,
    }
    proposal = {
        "kind": COMPARE_KIND,
        "handle": handle,
        **summary,
        "counts": counts,
        "partial": partial,
        "inline_limit": INLINE_ROWS_PER_SIDE,
    }
    return ToolOutput(json.dumps(answer, default=str, indent=1), proposal=proposal)


def build_file_compare_tools() -> tuple[Tool, ...]:
    """Offered when the router builds a ``FileCompareReader`` (``git.files:read`` and Nautobot)."""
    return (
        Tool(
            "list_file_repositories",
            "Git repositories the user can compare files from (category csv_imports or "
            "csv_exports): name, branch, category and last sync. Use it only when the "
            "repository is not clear; the compare tool needs no repository name when there "
            "is only one.",
            NoInput,
            _list_file_repositories,
        ),
        Tool(
            "compare_file_with_nautobot",
            "Compare a column of a CSV file in a git repository with a Nautobot device field "
            "(serial, name, primary_ip4, location, software_version) and find what is on only "
            "one side (file values no device has, device values that are not in the file) and what "
            "is on both sides (the matching rows, with their device). "
            "The server compares; you receive counts only and the user sees both lists in a "
            "card with a CSV download, so never repeat or guess values. Use filters to compare "
            "only some devices. If list_playbooks is available, read the playbook "
            "compare-file-with-nautobot first.",
            CompareFileInput,
            _compare_file_with_nautobot,
        ),
    )
