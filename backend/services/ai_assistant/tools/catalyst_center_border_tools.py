"""Border nodes and their handoffs for Ask the Net (doc/AI_TOOL_CHAIN.md §60).

One pure read, as the calling user: the SD-Access border nodes of Cisco Catalyst Center and, per
border, what it hands off to the outside (legacy) network: layer 3 handoffs to IP transits, to
SD-Access transits, and layer 2 handoffs.

Data sharing, fail closed: the inventory switch is checked before any request. The handoff
neighbour addresses (local/remote IPv4 and IPv6) need the addresses switch. Upstream error text
never reaches the model. The row field names are from the Cisco API reference, not yet verified
on a live fabric (doc/CISCO_CATALYST_INTEGRATION.md).
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from models.catalyst_center_facts import CatalystCenterBorderHandoffs
from services.ai_assistant.catalyst_center_reader import CatalystSource
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import (
    _SOURCE_ERRORS,
    _failure_sentence,
    _finish,
    _sources_or_error,
)
from services.catalyst_center.common.exceptions import CatalystCenterNotFoundError

DEFAULT_LIMIT = 3
MAX_LIMIT = 5  # a border with many handoffs is large: keep a page inside the tool output cap
MAX_ROWS_PER_KIND = 10
MAX_BORDERS = 1000
DEFAULT_TRANSITS = 25
MAX_TRANSITS = 40
MAX_CONTROL_PLANES = 10
_NOT_AVAILABLE = (
    "This Catalyst Center has no SD-Access API (an older release, or SD-Access is off)."
)
_ADDRESS_FIELDS = ("local_ip", "remote_ip", "local_ipv6", "remote_ipv6")

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BorderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_contains: Text | None = Field(
        None, description="Only border nodes whose hostname contains this text (any case)."
    )
    fabric_site: Text | None = Field(
        None, description="Only border nodes of this fabric site (exact hierarchy name)."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


def _rows(items: tuple[Any, ...], show_addresses: bool) -> dict[str, Any]:
    out = []
    for item in items[:MAX_ROWS_PER_KIND]:
        row = item.model_dump(exclude_none=True, exclude={"transit_id"})
        if not show_addresses:
            for key in _ADDRESS_FIELDS:
                row.pop(key, None)
        out.append(row)
    shown: dict[str, Any] = {"count": len(items), "items": out}
    if len(items) > MAX_ROWS_PER_KIND:
        shown["truncated"] = True
    return shown


def _border_entry(
    border: Any, record: Any, handoffs: CatalystCenterBorderHandoffs, show_addresses: bool
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "hostname": record.hostname if record else None,
        "device_id": border.device_id,
        "fabric_site": border.fabric_site,
        "roles": list(border.roles),
        "layer3_ip_transit_handoffs": _rows(handoffs.ip_transits, show_addresses),
        "layer3_sda_transit_handoffs": _rows(handoffs.sda_transits, show_addresses),
        "layer2_handoffs": _rows(handoffs.layer2, show_addresses),
    }
    if show_addresses and record is not None:
        entry["management_ip"] = record.management_ip
    if handoffs.unavailable:
        entry["unavailable"] = list(handoffs.unavailable)
    return entry


def _failed_entry(border: Any, record: Any, error: BaseException) -> dict[str, Any]:
    if not isinstance(error, _SOURCE_ERRORS):
        raise error  # a programming error is not a controller failure
    return {
        "hostname": record.hostname if record else None,
        "device_id": border.device_id,
        "fabric_site": border.fabric_site,
        "roles": list(border.roles),
        "error": _failure_sentence(error),
    }


async def _source_result(
    source: CatalystSource, border_service: Any, args: BorderInput, show_addresses: bool
) -> dict[str, Any]:
    borders, incomplete = await border_service.list_borders(fabric_site=args.fabric_site)
    borders_truncated = len(borders) > MAX_BORDERS
    if borders_truncated:
        borders = borders[:MAX_BORDERS]
    inventory = {
        d.id: d for d in await source.devices.get_devices_by_ids([b.device_id for b in borders])
    }
    needle = args.name_contains.lower() if args.name_contains else None
    kept = [
        b
        for b in borders
        if needle is None
        or needle in (getattr(inventory.get(b.device_id), "hostname", "") or "").lower()
    ]
    kept.sort(
        key=lambda b: (
            (getattr(inventory.get(b.device_id), "hostname", "") or "").lower(),
            b.device_id,
        )
    )
    page = kept[args.offset : args.offset + args.limit]
    transits = await border_service.list_transits() if page else {}
    # One failing border must not discard the others: a failure is that border's own entry.
    handoffs = await asyncio.gather(
        *(border_service.read_handoffs(b, transits) for b in page), return_exceptions=True
    )
    result: dict[str, Any] = {
        "source_id": source.source_id,
        "total": len(kept),
        "has_more": args.offset + args.limit < len(kept),
        "borders": [
            _border_entry(b, inventory.get(b.device_id), h, show_addresses)
            if isinstance(h, CatalystCenterBorderHandoffs)
            else _failed_entry(b, inventory.get(b.device_id), h)
            for b, h in zip(page, handoffs, strict=True)
        ],
    }
    if borders_truncated:
        result["truncated"] = True
        result["truncated_note"] = (
            f"Only the first {MAX_BORDERS} border nodes were searched; the answer may be partial."
        )
    if incomplete:
        result["incomplete_sites"] = list(incomplete)
    return result


async def _list_borders(ctx: ToolContext, args: BorderInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    show_addresses = ctx.sharing.allows(DataClass.ADDRESSES)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            if source.border is None:  # pragma: no cover - the reader always builds it
                raise CatalystCenterNotFoundError()
            results.append(await _source_result(source, source.border, args, show_addresses))
        except CatalystCenterNotFoundError:
            errors.append({"source_id": source.source_id, "error": _NOT_AVAILABLE})
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    if not show_addresses:
        message = not_shared_marker(DataClass.ADDRESSES)["message"]
        payload["withheld_fields"] = dict.fromkeys((*_ADDRESS_FIELDS, "management_ip"), message)
    if all(not r["total"] for r in results):
        payload["message"] = "No SD-Access border node was found on this Catalyst Center."
    return _finish(ctx, payload)


class TransitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transit_type: (
        Literal["IP_BASED_TRANSIT", "SDA_LISP_PUB_SUB_TRANSIT", "SDA_LISP_BGP_TRANSIT"] | None
    ) = Field(
        None,
        description="Only this kind: IP_BASED_TRANSIT (to the legacy/WAN side) or one of the "
        "SD-Access transits that connect fabrics.",
    )
    name_contains: Text | None = Field(
        None, description="Only transits whose name contains this text (any case)."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_TRANSITS)] = DEFAULT_TRANSITS
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


def _transit_row(transit: Any, hostnames: dict[str, str]) -> dict[str, Any]:
    row = transit.model_dump(
        exclude_none=True, exclude={"id", "control_plane_device_ids", "multicast_over_transit"}
    )
    if transit.multicast_over_transit is not None:
        row["multicast_over_transit"] = transit.multicast_over_transit
    ids = transit.control_plane_device_ids
    if ids:
        row["control_plane_count"] = len(ids)
        row["control_plane_devices"] = [hostnames.get(i, i) for i in ids[:MAX_CONTROL_PLANES]]
    return row


async def _transit_result(
    source: CatalystSource, border_service: Any, args: TransitInput
) -> dict[str, Any]:
    transits = list((await border_service.list_transits(missing_ok=False)).values())
    needle = args.name_contains.lower() if args.name_contains else None
    kept = [
        t
        for t in transits
        if (args.transit_type is None or t.transit_type == args.transit_type)
        and (needle is None or needle in (t.name or "").lower())
    ]
    kept.sort(key=lambda t: ((t.name or "").lower(), t.id))
    page = kept[args.offset : args.offset + args.limit]
    wanted = list(
        dict.fromkeys(i for t in page for i in t.control_plane_device_ids[:MAX_CONTROL_PLANES])
    )
    inventory = await source.devices.get_devices_by_ids(wanted) if wanted else ()
    hostnames = {d.id: d.hostname for d in inventory if d.hostname}
    return {
        "source_id": source.source_id,
        "total": len(kept),
        "has_more": args.offset + args.limit < len(kept),
        "transits": [_transit_row(t, hostnames) for t in page],
    }


async def _list_transits(ctx: ToolContext, args: TransitInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            if source.border is None:  # pragma: no cover - the reader always builds it
                raise CatalystCenterNotFoundError()
            results.append(await _transit_result(source, source.border, args))
        except CatalystCenterNotFoundError:
            errors.append({"source_id": source.source_id, "error": _NOT_AVAILABLE})
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    if all(not r["total"] for r in results):
        payload["message"] = "No transit network is configured on this Catalyst Center."
    return _finish(ctx, payload)


def build_catalyst_center_border_tools() -> tuple[Tool, ...]:
    async def run(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_borders(ctx, args)

    async def transits(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_transits(ctx, args)

    return (
        Tool(
            "list_catalyst_center_border_handoffs",
            "List the SD-Access border nodes of Cisco Catalyst Center and what each hands off to "
            "the outside (legacy) network: layer 3 handoffs to IP transits (interface, virtual "
            "network, VLAN, IP pool, local/remote address), layer 3 handoffs to SD-Access "
            "transits (internet, multicast) and layer 2 handoffs (interface, internal/external "
            "VLAN). Use it for 'what is the exchange point between the fabric and the legacy "
            "network' and 'which handoffs does border X have'. Narrow with name_contains or "
            "fabric_site; borders are paged (limit max 5). A kind in 'unavailable' could not be "
            "read for that border: say the list is partial. It is the controller's configured "
            "view, not a live check. Needs the inventory data switch; neighbour addresses and "
            "management IPs also need the addresses switch.",
            BorderInput,
            run,
        ),
        Tool(
            "list_catalyst_center_transits",
            "List the SD-Access transit networks of Cisco Catalyst Center: IP transits (to the "
            "legacy or WAN side; routing protocol and AS number) and SD-Access transits that "
            "connect fabrics (multicast over transit, control plane devices). Use it for 'which "
            "transits exist'. Which borders use a transit is in list_catalyst_center_border_"
            "handoffs. Narrow with transit_type or name_contains; page with limit/offset. It is "
            "the controller's configured view. Needs the inventory data switch.",
            TransitInput,
            transits,
        ),
    )
