"""SD-Access virtual networks for Ask the Net (doc/AI_TOOL_CHAIN.md §59).

One pure read, as the calling user: the layer 3 virtual networks of Cisco Catalyst Center (VRFs
such as ``INFRA_VN``) with the fabric sites they are deployed to, and their layer 2 VLANs.

Data sharing, fail closed: the inventory switch is checked before any request. Network names,
VLAN ids and fabric sites carry no addresses or free text. Upstream error text never reaches the
model.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from models.catalyst_center_facts import CatalystCenterVirtualNetworks
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import (
    _SOURCE_ERRORS,
    _failure_sentence,
    _finish,
    _sources_or_error,
)
from services.catalyst_center.common.exceptions import CatalystCenterNotFoundError

DEFAULT_LIMIT = 25
MAX_LIMIT = 50
MAX_VLANS_PER_NETWORK = 10
MAX_OTHER_VLANS = 20
_NOT_AVAILABLE = (
    "This Catalyst Center has no SD-Access API (an older release, or SD-Access is off)."
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class VirtualNetworksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_contains: Text | None = Field(
        None, description="Only virtual networks whose name contains this text (any case)."
    )
    fabric_site: Text | None = Field(
        None, description="Only networks deployed to this fabric site (exact hierarchy name)."
    )
    include_layer2: bool = Field(True, description="Also the layer 2 VLANs of each network.")
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


def _vlan(v: Any) -> dict[str, Any]:
    return v.model_dump(exclude_none=True, exclude={"layer3_virtual_network"})


def _source_result(
    source_id: str, found: CatalystCenterVirtualNetworks, args: VirtualNetworksInput
) -> dict[str, Any]:
    needle = args.name_contains.lower() if args.name_contains else None
    networks = [
        n
        for n in found.networks
        if (needle is None or needle in n.name.lower())
        and (args.fabric_site is None or args.fabric_site in n.fabric_sites)
    ]
    networks.sort(key=lambda n: n.name.lower())
    by_network: dict[str, list[Any]] = {}
    for vlan in found.layer2:
        by_network.setdefault((vlan.layer3_virtual_network or "").lower(), []).append(vlan)
    rows: list[dict[str, Any]] = []
    for n in networks[args.offset : args.offset + args.limit]:
        row: dict[str, Any] = {
            "name": n.name,
            "deployed": bool(n.fabric_sites),
            "fabric_sites": list(n.fabric_sites),
        }
        if args.include_layer2 and found.layer2_available:
            vlans = [
                v
                for v in by_network.get(n.name.lower(), [])
                if args.fabric_site is None or v.fabric_site == args.fabric_site
            ]
            row["layer2_count"] = len(vlans)
            row["layer2_networks"] = [_vlan(v) for v in vlans[:MAX_VLANS_PER_NETWORK]]
        rows.append(row)
    result: dict[str, Any] = {
        "source_id": source_id,
        "total": len(networks),
        "has_more": args.offset + args.limit < len(networks),
        "virtual_networks": rows,
    }
    if args.include_layer2 and not found.layer2_available:
        result["layer2_note"] = "This controller does not offer the layer 2 virtual network API."
    known = {n.name.lower() for n in found.networks}
    orphans = [
        v
        for v in found.layer2
        if (v.layer3_virtual_network or "").lower() not in known
        and (args.fabric_site is None or v.fabric_site == args.fabric_site)
    ]
    if args.include_layer2 and args.name_contains is None and orphans:
        result["layer2_without_virtual_network_count"] = len(orphans)
        result["layer2_without_virtual_network"] = [_vlan(v) for v in orphans[:MAX_OTHER_VLANS]]
    return result


async def _list_virtual_networks(ctx: ToolContext, args: VirtualNetworksInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            if source.fabric is None:  # pragma: no cover - the reader always builds it
                raise CatalystCenterNotFoundError()
            found = await source.fabric.list_virtual_networks()
        except CatalystCenterNotFoundError:
            errors.append({"source_id": source.source_id, "error": _NOT_AVAILABLE})
            continue
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            continue
        results.append(_source_result(source.source_id, found, args))
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    return _finish(ctx, payload)


def build_catalyst_center_vn_tools() -> tuple[Tool, ...]:
    async def run(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_virtual_networks(ctx, args)

    return (
        Tool(
            "list_catalyst_center_virtual_networks",
            "List the SD-Access virtual networks of Cisco Catalyst Center: the layer 3 networks "
            "(VRFs such as INFRA_VN, DEFAULT_VN) with the fabric sites each is deployed to "
            "(deployed=false: defined but in no fabric site), and their layer 2 VLANs (name, "
            "VLAN id, traffic type, fabric site). Narrow with name_contains or fabric_site; "
            "page with limit/offset. It is the controller's configured view, not a live check. "
            "Needs the inventory data switch.",
            VirtualNetworksInput,
            run,
        ),
    )
