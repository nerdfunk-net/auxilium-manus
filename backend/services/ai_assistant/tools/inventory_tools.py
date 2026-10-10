"""Tools for the inventory surface: answer questions about saved inventories and devices.

Pure reads over Nautobot data as the calling user. Everything that identifies or describes devices
is class B (inventory data) and is replaced by a ``not_shared`` marker unless the user opted in;
only the size of an inventory is always shown.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.data_sharing import (
    DataClass,
    SharingPolicy,
    filter_nautobot_attributes,
    gated,
    not_shared_marker,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

MAX_DEVICES_LISTED = 50
MAX_FIELD_CHARS = 500
GROUPING_FIELDS = ("role", "platform", "location", "status", "device_type", "manufacturer")
TOP_GROUP_VALUES = 15
DEVICE_FIELDS = (
    "id",
    "name",
    "location",
    "role",
    "platform",
    "status",
    "device_type",
    "manufacturer",
    "primary_ip4",
    "serial",
    "tags",
    "custom_fields",
)


class InventoryAccessError(Exception):
    """The calling user may not read Nautobot data, or the source is unavailable."""


class InventoryNotFoundError(Exception):
    """No such inventory, or it is private to someone else (indistinguishable on purpose)."""


class InventoryReader(Protocol):
    async def list_inventories(self) -> list[dict[str, Any]]: ...

    async def resolve_inventory(self, inventory_id: int) -> dict[str, Any]: ...

    async def search_devices(self, search: str, limit: int) -> list[dict[str, Any]]: ...

    async def get_device_attributes(
        self, device_id: str, attributes: list[str] | None
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class InventoryState:
    reader: InventoryReader


def _state(ctx: ToolContext) -> InventoryState:
    return ctx.extras["inventory"]


# -- inputs -----------------------------------------------------------------------------------


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_id: int = Field(ge=1)
    limit: int = Field(default=20, ge=1, le=MAX_DEVICES_LISTED)
    fields: list[str] = Field(
        default_factory=lambda: ["name", "role", "platform", "location"],
        max_length=len(DEVICE_FIELDS),
        description=f"Device fields to return, from: {', '.join(DEVICE_FIELDS)}",
    )


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: str = Field(min_length=1, max_length=100, description="Part of the device name")
    limit: int = Field(default=20, ge=1, le=MAX_DEVICES_LISTED)


class AttributesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=100, description="Device id from a result")
    attributes: list[str] | None = Field(
        default=None, max_length=50, description="Only these Nautobot attributes; omit for all"
    )


# -- helpers ----------------------------------------------------------------------------------

_NOT_FOUND = ToolOutput("That inventory does not exist or you cannot access it.", is_error=True)
_NO_ACCESS = ToolOutput(
    "You cannot read Nautobot data here (missing permission or the source is unavailable).",
    is_error=True,
)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, indent=1)


def _cap(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS] + "…" if len(value) > MAX_FIELD_CHARS else value
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


# Device fields that need more than the base inventory switch.
_FIELD_CLASS: dict[str, DataClass] = {
    "primary_ip4": DataClass.ADDRESSES,
    "serial": DataClass.ADDRESSES,
    "custom_fields": DataClass.CUSTOM_FIELDS,
}


def _allowed_fields(policy: SharingPolicy, fields: list[str]) -> tuple[list[str], dict[str, str]]:
    """Requested fields the user's opt-ins allow, plus the ones withheld and which setting
    releases them."""
    allowed = ["id"]
    withheld: dict[str, str] = {}
    for name in fields:
        if name not in DEVICE_FIELDS or name == "id":
            continue
        needed = _FIELD_CLASS.get(name)
        if needed is None or policy.allows(needed):
            allowed.append(name)
        else:
            withheld[name] = not_shared_marker(needed)["not_shared"]
    return allowed, withheld


def _project(device: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {f: device.get(f) for f in fields}


def _group_counts(devices: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for field_name in GROUPING_FIELDS:
        counts = Counter(str(d.get(field_name) or "(none)") for d in devices)
        out[field_name] = dict(counts.most_common(TOP_GROUP_VALUES))
    return out


# -- handlers ---------------------------------------------------------------------------------


async def _list_inventories(ctx: ToolContext, args: NoInput) -> ToolOutput:
    try:
        rows = await _state(ctx).reader.list_inventories()
    except InventoryAccessError:
        return _NO_ACCESS
    if not rows:
        return ToolOutput("No saved inventories are available to you.")
    return ToolOutput("\n".join(json.dumps(r, default=str) for r in rows))


async def _resolve_inventory(ctx: ToolContext, args: ResolveInput) -> ToolOutput:
    try:
        resolved = await _state(ctx).reader.resolve_inventory(args.inventory_id)
    except InventoryNotFoundError:
        return _NOT_FOUND
    except InventoryAccessError:
        return _NO_ACCESS
    devices: list[dict[str, Any]] = resolved["devices"]
    truncated = False
    result: dict[str, Any] = {
        "inventory": {k: resolved.get(k) for k in ("id", "name", "inventory_type")},
        "total_count": len(devices),
    }
    if ctx.sharing.allows(DataClass.INVENTORY):
        fields, withheld = _allowed_fields(ctx.sharing, args.fields)
        result["counts_by"] = _group_counts(devices)
        result["devices"] = [_project(d, fields) for d in devices[: args.limit]]
        if withheld:
            result["withheld_fields"] = withheld  # field -> setting the user has not enabled
        if len(devices) > args.limit:
            truncated = True
            result["note"] = (
                f"Showing {args.limit} of {len(devices)} devices; counts_by covers all of them."
            )
    else:
        result["devices"] = not_shared_marker(DataClass.INVENTORY)
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(result))), truncated=truncated)


async def _search_devices(ctx: ToolContext, args: SearchInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(_json(not_shared_marker(DataClass.INVENTORY)))
    try:
        devices = await _state(ctx).reader.search_devices(args.search, args.limit)
    except InventoryAccessError:
        return _NO_ACCESS
    if not devices:
        return ToolOutput("No devices match.")
    fields, _withheld = _allowed_fields(
        ctx.sharing, ["name", "role", "platform", "location", "primary_ip4"]
    )
    rows = [_project(d, fields) for d in devices]
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(rows))))


async def _get_device_attributes(ctx: ToolContext, args: AttributesInput) -> ToolOutput:
    shared = gated(ctx.sharing, DataClass.INVENTORY, True)
    if shared is not True:
        return ToolOutput(_json(shared))
    # Fixed allow-list: attributes the model asks for by name are filtered the same way.
    try:
        attributes = await _state(ctx).reader.get_device_attributes(args.device_id, args.attributes)
    except InventoryNotFoundError:
        return ToolOutput(f"Device '{args.device_id}' not found.", is_error=True)
    except InventoryAccessError:
        return _NO_ACCESS
    kept, withheld = filter_nautobot_attributes(ctx.sharing, attributes)
    result: dict[str, Any] = {"attributes": kept}
    if withheld:
        # attribute -> the setting that releases it, or "never" for unknown attributes
        result["withheld_attributes"] = withheld
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(result))))


INVENTORY_TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_inventories",
        "Saved inventories available to the user: id, name, type (filter or static), scope.",
        NoInput,
        _list_inventories,
    ),
    Tool(
        "resolve_inventory",
        "Devices of one saved inventory (resolved against Nautobot now): total_count, counts by "
        "role / platform / location / status for ALL devices, and up to `limit` devices with the "
        "requested fields. Use the counts for 'how many' questions.",
        ResolveInput,
        _resolve_inventory,
    ),
    Tool(
        "search_devices",
        "Find devices by part of their name across Nautobot (not limited to one inventory).",
        SearchInput,
        _search_devices,
    ),
    Tool(
        "get_device_attributes",
        "Nautobot attributes of one device (by id from another result), optionally only some. "
        "Addresses, custom fields and config context are returned only if the user enabled them; "
        "withheld_attributes says which and why.",
        AttributesInput,
        _get_device_attributes,
    ),
)
