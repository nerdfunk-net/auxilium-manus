"""SD-Access overlay / underlay membership for Ask the Net (doc/AI_TOOL_CHAIN.md §57).

One pure read, as the calling user: which devices Cisco Catalyst Center says are part of the
SD-Access overlay (a fabric role: border, control plane, edge, ...) or of the underlay (those
devices plus the role-less intermediate nodes of the fabric sites).

Data sharing (doc/ai_integration/AI_ASSISTANT.md §4), fail closed: the inventory switch is
checked before any request; management addresses and serials need the addresses switch.
Upstream error text never reaches the model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from models.catalyst_center_facts import CatalystCenterFabric
from services.ai_assistant.catalyst_center_reader import CatalystSource
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import (
    _SOURCE_ERRORS,
    _failure_sentence,
    _finish,
    _sources_or_error,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterTooManyDevicesError,
    CatalystCenterTooManySitesError,
    CatalystCenterUnknownSiteError,
)
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters

DEFAULT_LIMIT = 25
MAX_LIMIT = 40  # a row is ~350 characters; the tool output cap is 20,000
MAX_LISTED = 20  # fabric sites and virtual networks named per source
DEFAULT_SITES = 100
SITE_DEVICE_CAP = 1000
MAX_SITES = 200
_NOT_AVAILABLE = (
    "This Catalyst Center has no SD-Access API (an older release, or SD-Access is off)."
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_ADDRESS_FIELDS = ("management_ip", "serial_number")


class FabricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: Literal["overlay", "underlay"] = Field(
        "overlay",
        description="overlay: devices with an SD-Access fabric role. underlay: those devices "
        "and the intermediate nodes of the fabric sites that have no fabric role.",
    )
    fabric_site: Text | None = Field(
        None,
        description="Only this fabric site, by its hierarchy name (e.g. 'Global/EMEA/Berlin').",
    )
    role: Text | None = Field(
        None,
        description="Only devices with this role, e.g. BORDER_NODE, EDGE_NODE, CONTROL_PLANE_NODE.",
    )
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


def _rows(fabric: CatalystCenterFabric, args: FabricInput) -> list[dict[str, Any]]:
    rows = [
        {
            "device_id": d.device_id,
            "fabric_site": d.fabric_site,
            "roles": list(d.roles),
            "in_overlay": bool(d.roles),
            "in_underlay": True,
        }
        for d in fabric.devices
    ]
    if args.network == "underlay":
        rows += [
            {
                "device_id": u.device_id,
                "fabric_site": u.fabric_site,
                "roles": [],
                "in_overlay": False,
                "in_underlay": True,
            }
            for u in fabric.underlay_only
        ]
    else:
        rows = [r for r in rows if r["in_overlay"]]
    if args.fabric_site:
        rows = [r for r in rows if r["fabric_site"] == args.fabric_site]
    if args.role:
        wanted = args.role.upper()
        rows = [r for r in rows if wanted in r["roles"]]
    return sorted(rows, key=lambda r: (r["fabric_site"] or "", r["device_id"]))


async def _source_result(
    source: CatalystSource, fabric_service: Any, args: FabricInput, show_addresses: bool
) -> dict[str, Any]:
    fabric = await fabric_service.read_fabric(
        include_underlay=args.network == "underlay", fabric_site=args.fabric_site
    )
    rows = _rows(fabric, args)
    page = rows[args.offset : args.offset + args.limit]
    inventory = {
        d.id: d for d in await source.devices.get_devices_by_ids([r["device_id"] for r in page])
    }
    devices = []
    for row in page:
        record = inventory.get(row["device_id"])
        entry = {
            **row,
            "hostname": record.hostname if record else None,
            "platform_id": record.platform_id if record else None,
            "reachability_status": record.reachability_status if record else None,
        }
        if show_addresses:
            entry["management_ip"] = record.management_ip if record else None
            entry["serial_number"] = record.serial_number if record else None
        devices.append(entry)
    names = [s.site_name for s in fabric.sites]
    networks = [
        {"name": n.name, "fabric_sites": list(n.fabric_sites[:MAX_LISTED])}
        for n in fabric.virtual_networks
    ]
    result: dict[str, Any] = {
        "source_id": source.source_id,
        "total": len(rows),
        "has_more": args.offset + args.limit < len(rows),
        # The rows come first and the lists are capped: an over-long answer is cut from the end.
        "devices": devices,
        "fabric_site_count": len(names),
        "fabric_sites": names[:MAX_LISTED],
        "virtual_network_count": len(networks),
        "virtual_networks": networks[:MAX_LISTED],
    }
    if fabric.incomplete_sites:
        result["incomplete_sites"] = list(fabric.incomplete_sites)
        result["incomplete_note"] = (
            "These fabric sites could not be read completely; their device list is partial."
        )
    return result


async def _list_fabric(ctx: ToolContext, args: FabricInput) -> ToolOutput:
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
            if source.fabric is None:  # pragma: no cover - the reader always builds it
                raise CatalystCenterNotFoundError()
            results.append(await _source_result(source, source.fabric, args, show_addresses))
        except CatalystCenterNotFoundError:
            errors.append({"source_id": source.source_id, "error": _NOT_AVAILABLE})
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"network": args.network, "sources": results}
    if errors:
        payload["source_errors"] = errors
    if not show_addresses:
        withheld: Mapping[str, str] = dict.fromkeys(
            _ADDRESS_FIELDS, not_shared_marker(DataClass.ADDRESSES)["message"]
        )
        payload["withheld_fields"] = dict(withheld)
    if all(not r["fabric_site_count"] for r in results):
        payload["message"] = "No SD-Access fabric site is configured on this Catalyst Center."
    return _finish(ctx, payload)


class SitesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_contains: Text | None = Field(
        None, description="Only sites whose hierarchy name contains this text (any case)."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_SITES)] = DEFAULT_SITES
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


async def _list_sites(ctx: ToolContext, args: SitesInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    needle = args.name_contains.lower() if args.name_contains else None
    for source in sources:
        try:
            sites = await source.devices.list_sites()
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            continue
        names = sorted(
            site.name_hierarchy
            for site in sites
            if needle is None or needle in site.name_hierarchy.lower()
        )
        results.append(
            {
                "source_id": source.source_id,
                "total": len(names),
                "has_more": args.offset + args.limit < len(names),
                "sites": names[args.offset : args.offset + args.limit],
            }
        )
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    return _finish(ctx, payload)


class SiteDevicesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Text = Field(
        description="Exact site hierarchy name, e.g. 'Global/EMEA/Berlin' "
        "(see list_catalyst_center_sites).",
    )
    include_child_sites: bool = Field(True, description="Also devices of the sub-sites.")
    role: Text | None = Field(
        None, description="Only devices with this controller role, exact spelling (e.g. ACCESS)."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


_BAD_SITE = (
    "The site is not a known Catalyst Center site. Call list_catalyst_center_sites and use "
    "the exact name."
)
_TOO_MANY_SITES = "The site has too many sub-sites to read at once; ask for a sub-site."
_TOO_MANY = (
    f"The site holds more than {SITE_DEVICE_CAP} devices; narrow it with a sub-site or role."
)


async def _list_site_devices(ctx: ToolContext, args: SiteDevicesInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    show_addresses = ctx.sharing.allows(DataClass.ADDRESSES)
    filters = CatalystCenterDeviceFilters(
        sites=(args.site,),
        include_child_sites=args.include_child_sites,
        roles=(args.role,) if args.role else (),
    )
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            found = await source.devices.search_devices(filters, max_devices=SITE_DEVICE_CAP)
        except CatalystCenterTooManyDevicesError:
            errors.append({"source_id": source.source_id, "error": _TOO_MANY})
            continue
        except CatalystCenterUnknownSiteError:
            # Not an error for a controller that simply lacks the site.
            errors.append({"source_id": source.source_id, "error": _BAD_SITE})
            continue
        except CatalystCenterTooManySitesError:
            errors.append({"source_id": source.source_id, "error": _TOO_MANY_SITES})
            continue
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            continue
        ordered = sorted(found, key=lambda d: ((d.hostname or "").lower(), d.id))
        devices = []
        for d in ordered[args.offset : args.offset + args.limit]:
            entry: dict[str, Any] = {
                "hostname": d.hostname,
                "role": d.role,
                "platform_id": d.platform_id,
                "software_version": d.software_version,
                "reachability_status": d.reachability_status,
            }
            if show_addresses:
                entry["management_ip"] = d.management_ip
                entry["serial_number"] = d.serial_number
            devices.append(entry)
        results.append(
            {
                "source_id": source.source_id,
                "site": args.site,
                "total": len(ordered),
                "has_more": args.offset + args.limit < len(ordered),
                "devices": devices,
            }
        )
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    if not show_addresses:
        message = not_shared_marker(DataClass.ADDRESSES)["message"]
        payload["withheld_fields"] = dict.fromkeys(_ADDRESS_FIELDS, message)
    return _finish(ctx, payload)


def build_catalyst_center_fabric_tools() -> tuple[Tool, ...]:
    async def run(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_fabric(ctx, args)

    async def sites(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_sites(ctx, args)

    async def site_devices(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_site_devices(ctx, args)

    return (
        Tool(
            "list_catalyst_center_fabric",
            "Which devices are part of the SD-Access overlay or underlay, from Cisco Catalyst "
            "Center. network=overlay lists devices with a fabric role (border, control plane, "
            "edge, wireless controller, extended node), network=underlay also the intermediate "
            "nodes of the fabric sites that have no fabric role (every overlay device is in the "
            "underlay too). Also returns the fabric sites and virtual networks. Narrow with "
            "fabric_site or role; page with limit/offset. An empty fabric is an answer (no "
            "SD-Access), not an error. It is the controller's configured view, not a live "
            "check. Needs the inventory data switch; management IPs and serials also need the "
            "addresses switch.",
            FabricInput,
            run,
        ),
        Tool(
            "list_catalyst_center_sites",
            "List the sites configured in Cisco Catalyst Center (the site hierarchy: areas, "
            "buildings, floors, as 'Global/EMEA/Berlin'). Use it for 'list the sites of the "
            "Catalyst Center' and to find the exact name before using fabric_site. Narrow with "
            "name_contains; page with limit/offset. These are the controller's sites, not "
            "Nautobot locations. Needs the inventory data switch.",
            SitesInput,
            sites,
        ),
        Tool(
            "list_catalyst_center_devices",
            "List the devices assigned to a Cisco Catalyst Center site ('What devices are part "
            "of site X?'). Pass the exact site hierarchy name (get it from "
            "list_catalyst_center_sites); sub-sites are included unless include_child_sites is "
            "false. Narrow with role; page with limit/offset. Shows hostname, role, platform, "
            "software and reachability; management IPs and serials need the addresses switch. "
            "The controller's collected view, not a live check. Needs the inventory data switch.",
            SiteDevicesInput,
            site_devices,
        ),
    )
