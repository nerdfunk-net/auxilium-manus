"""Tools that let the inventory assistant build a filter: reference, value lookup, preview, propose.

``preview_filter`` is a pure read. ``propose_inventory`` is a proposal: it checks the filter and
shows it to the user, who applies it to the inventory builder as unsaved state and saves it
themselves. Nothing here persists an inventory (doc/ai_integration/AI_ASSISTANT.md §3.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from models.sources_nautobot import LogicalOperation
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.inventory_filter import (
    VALUE_LIST_FIELDS,
    FilterInput,
    build_condition_tree,
    canonicalize_values,
    conditions_of,
    field_data_class,
    structure_errors,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.inventory_tools import (
    _NO_ACCESS,
    InventoryAccessError,
    InventoryQueryError,
    _allowed_fields,
    _cap,
    _group_counts,
    _json,
    _project,
    _state,
)
from utils.inventory_converter import tree_to_operations

_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "inventory_reference.md"
MAX_VALUES_LISTED = 100
MAX_SAMPLE_DEVICES = 10
SAMPLE_FIELDS = ["name", "role", "location", "status", "primary_ip4"]


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldValuesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["location", "role", "status", "tag", "device_type", "manufacturer", "platform"]
    contains: str | None = Field(
        default=None, max_length=100, description="Only names containing this text"
    )


class ProposeInput(FilterInput):
    summary: str = Field(
        min_length=1,
        max_length=300,
        description="One line telling the user what the filter selects",
    )


_QUERY_FAILED = ToolOutput(
    "Nautobot could not evaluate the filter: a condition failed (Nautobot unreachable or the "
    "filter was rejected). Nothing was proposed and the result is not '0 devices'. Check the "
    "values, or tell the user to try again.",
    is_error=True,
)


@dataclass(frozen=True)
class _Prepared:
    tree: dict[str, Any]
    operations: list[LogicalOperation]
    warnings: list[str]
    # The data class the user has not shared that the filter would touch, if any. Running such a
    # filter and reporting a count would tell the model whether a guessed device name, address
    # or custom-field value exists, so a filter like that is checked but never run.
    withheld: DataClass | None = None


def _withheld_class(ctx: ToolContext, args: FilterInput) -> DataClass | None:
    needed = {DataClass.INVENTORY, *(field_data_class(c.field) for c in conditions_of(args))}
    for data_class in (DataClass.INVENTORY, DataClass.ADDRESSES, DataClass.CUSTOM_FIELDS):
        if data_class in needed and not ctx.sharing.allows(data_class):
            return data_class
    return None


def _invalid(errors: list[str]) -> ToolOutput:
    listing = "\n".join(f"- {e}" for e in errors)
    return ToolOutput(f"The filter is invalid:\n{listing}\nFix it and try again.", is_error=True)


async def _prepare(ctx: ToolContext, args: FilterInput) -> _Prepared | ToolOutput:
    """Check the filter, spell its values as Nautobot does and turn it into operations."""
    errors = structure_errors(args)
    if errors:
        return _invalid(errors)
    reader = _state(ctx).reader
    fields = sorted(
        {c.field for c in [*args.conditions, *(c for g in args.groups for c in g.conditions)]}
    )
    known: dict[str, list[dict[str, str]]] = {}
    try:
        for field in fields:
            if field in VALUE_LIST_FIELDS:
                known[field] = await reader.field_values(field)
    except InventoryAccessError:
        return _NO_ACCESS
    fixed, errors = canonicalize_values(
        args, known, show_names=ctx.sharing.allows(DataClass.INVENTORY)
    )
    if errors:
        return _invalid(errors)
    warnings = [
        f"The values of {field} could not be verified (Nautobot returned no list)."
        for field, rows in known.items()
        if not rows
    ]
    tree = build_condition_tree(fixed)
    return _Prepared(
        tree=tree,
        operations=tree_to_operations(tree),
        warnings=warnings,
        withheld=_withheld_class(ctx, args),
    )


async def _devices(ctx: ToolContext, prepared: _Prepared) -> list[dict[str, Any]] | ToolOutput:
    try:
        return await _state(ctx).reader.preview_operations(prepared.operations)
    except InventoryAccessError:
        return _NO_ACCESS
    except InventoryQueryError:
        return _QUERY_FAILED


async def _get_inventory_reference(ctx: ToolContext, args: NoInput) -> ToolOutput:
    return ToolOutput(_REFERENCE_PATH.read_text(encoding="utf-8"))


async def _list_field_values(ctx: ToolContext, args: FieldValuesInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(_json(not_shared_marker(DataClass.INVENTORY)))
    try:
        rows = await _state(ctx).reader.field_values(args.field)
    except InventoryAccessError:
        return _NO_ACCESS
    names = [str(r["value"]) for r in rows]
    if args.contains:
        needle = args.contains.lower()
        names = [n for n in names if needle in n.lower()]
    result: dict[str, Any] = {
        "field": args.field,
        "total": len(names),
        "values": names[:MAX_VALUES_LISTED],
    }
    if len(names) > MAX_VALUES_LISTED:
        result["note"] = f"Showing {MAX_VALUES_LISTED}; narrow it with `contains`."
    return ToolOutput(
        _json(_cap(ctx.redactor.redact_data(result))), truncated=len(names) > MAX_VALUES_LISTED
    )


def _summary(ctx: ToolContext, devices: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"total_count": len(devices)}
    if ctx.sharing.allows(DataClass.INVENTORY):
        fields, _withheld = _allowed_fields(ctx.sharing, SAMPLE_FIELDS)
        result["counts_by"] = _group_counts(devices)
        result["devices"] = [_project(d, fields) for d in devices[:MAX_SAMPLE_DEVICES]]
    else:
        result["devices"] = not_shared_marker(DataClass.INVENTORY)
    return result


async def _preview_filter(ctx: ToolContext, args: FilterInput) -> ToolOutput:
    prepared = await _prepare(ctx, args)
    if isinstance(prepared, ToolOutput):
        return prepared
    if prepared.withheld is not None:
        result: dict[str, Any] = {
            "valid": True,
            "total_count": not_shared_marker(prepared.withheld),
        }
        return ToolOutput(_json(result))
    devices = await _devices(ctx, prepared)
    if isinstance(devices, ToolOutput):
        return devices
    result = _summary(ctx, devices)
    if prepared.warnings:
        result["warnings"] = prepared.warnings
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(result))))


async def _propose_inventory(ctx: ToolContext, args: ProposeInput) -> ToolOutput:
    prepared = await _prepare(ctx, args)
    if isinstance(prepared, ToolOutput):
        return prepared
    total_count: int | None = None
    if prepared.withheld is None:
        devices = await _devices(ctx, prepared)
        if isinstance(devices, ToolOutput):
            return devices
        total_count = len(devices)
    proposal = {
        "kind": "inventory",
        "summary": args.summary,
        "tree": prepared.tree,
        "total_count": total_count,
        "warnings": prepared.warnings,
    }
    shown = (
        f"The filter matches {total_count} devices."
        if total_count is not None
        else "The device count is not shared with you (see below), so the user sees it only in "
        "the builder."
    )
    message = (
        f"{shown} It was shown to the user with Apply/Reject and is NOT applied yet; do not say "
        "it was. They review it in the inventory builder and save it themselves. Briefly say "
        "what it selects."
    )
    if prepared.withheld is not None:
        marker = not_shared_marker(prepared.withheld)
        message += f" Count withheld: {marker['message']}"
    if total_count == 0:
        message += " It matches 0 devices: tell the user."
    if prepared.warnings:
        message += " Warnings: " + " ".join(prepared.warnings)
    return ToolOutput(message, proposal=proposal)


_FILTER_HELP = (
    "A filter: `logic` (AND/OR) combining `conditions` [{field, operator, value}] and `groups` "
    "[{logic, negate, conditions}]. Read get_inventory_reference first."
)

INVENTORY_FILTER_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_inventory_reference",
        "How the inventory builder selects devices: fields, operators per field, value formats, "
        "AND/OR/NOT, recipes. Read it before your first filter.",
        NoInput,
        _get_inventory_reference,
    ),
    Tool(
        "list_field_values",
        "Nautobot's real names for a filter field (location, role, status, tag, device_type, "
        "manufacturer, platform). Use it to find the exact value for what the user said.",
        FieldValuesInput,
        _list_field_values,
    ),
    Tool(
        "preview_filter",
        "Run a filter now without proposing it: returns total_count and, if the user shares "
        "inventory data, counts by role/platform/location/status and a few sample devices. "
        f"{_FILTER_HELP}",
        FilterInput,
        _preview_filter,
    ),
    Tool(
        "propose_inventory",
        "Propose a filter as a new inventory. The filter is checked (operators, real values) and "
        "shown to the user, who applies it to the builder and saves it; you cannot save. "
        f"{_FILTER_HELP} Also needs a one-line `summary`.",
        ProposeInput,
        _propose_inventory,
    ),
)
