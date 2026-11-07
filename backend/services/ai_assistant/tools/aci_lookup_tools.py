"""ACI endpoint and subnet lookups for Ask the Net (doc/plans/ACI_TOOL_CHAIN.md, phase 2).

Also ``list_aci_endpoints`` (the learned endpoints of a tenant, profile or EPG) and
``get_aci_endpoint_history`` (when the APIC learned and last changed an endpoint, and the events
and faults that name it).

``find_aci_endpoint``: where an IPv4 or MAC address was learned in the fabric (the APIC's
current view). ``list_aci_subnets``: which bridge domain / VRF owns a gateway subnet, filtered
by an address inside it, a prefix, tenant, VRF or bridge domain.

Both need the inventory and the addresses switch for the whole call, checked before any
request (otherwise existence would leak). The field rules and fixed error sentences are the
ones of ``aci_tools``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from models.aci_endpoint import AciEndpoint
from models.aci_subnets import AciSubnet
from services.aci.common.exceptions import AciValidationError
from services.aci.endpoint_service import MAX_EVENTS
from services.ai_assistant.aci_reader import AciSource
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.aci_fields import project
from services.ai_assistant.tools.aci_tools import (
    _SOURCE_ERRORS,
    COST_FULL_SUBNET_READ,
    Text,
    _failure_sentence,
    _finish,
    _SourceInput,
    _sources_or_error,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import PREVIEW_ROWS

_BAD_ADDRESS = ToolOutput(
    "The address is not valid: give an IPv4 address or a MAC address.", is_error=True
)


def _gate(ctx: ToolContext) -> ToolOutput | None:
    for data_class in (DataClass.INVENTORY, DataClass.ADDRESSES):
        if not ctx.sharing.allows(data_class):
            return ToolOutput(_json_marker(data_class))
    return None


def _json_marker(data_class: DataClass) -> str:
    return json.dumps(not_shared_marker(data_class), indent=1)


COST_ENDPOINT_LISTING = 2
HISTORY_NOTE = (
    "The APIC keeps no move history. These are the timestamps of the endpoint's current records "
    "and the event and fault log lines that name its MAC or addresses. A 'last_changed' is the "
    "last time the record changed (a move, a re-learn, an address change), not the first time the "
    "host was seen. For moves over time use an endpoint tracker or a flow collector."
)


class ListEndpointsInput(_SourceInput):
    tenant: Text = Field(description="The tenant whose learned endpoints to list.")
    app_profile: Text | None = Field(None, description="Only this application profile.")
    epg: Text | None = Field(None, description="Only this EPG (needs app_profile).")
    within: Text | None = Field(
        None, description="Only endpoints with an address in this prefix (10.1.0.0/16)."
    )
    limit: Annotated[int, Field(ge=1, le=PREVIEW_ROWS)] = PREVIEW_ROWS
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0

    @model_validator(mode="after")
    def _epg_needs_profile(self) -> ListEndpointsInput:
        if self.epg is not None and self.app_profile is None:
            raise ValueError("an EPG needs its application profile")
        return self

    @field_validator("within")
    @classmethod
    def _net(cls, value: str | None) -> str | None:
        if value is not None:
            _network(value)
        return value


class EndpointHistoryInput(_SourceInput):
    address: Text = Field(description="An IPv4 address or a MAC address in any notation.")


class FindEndpointInput(_SourceInput):
    address: Text = Field(
        description="An IPv4 address (10.1.1.5) or a MAC address in any notation "
        "(aa:bb:cc:00:01:00, aabb.cc00.0100)."
    )


def _network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(value, strict=False)


class ListSubnetsInput(_SourceInput):
    contains_ip: Text | None = Field(None, description="Only subnets that contain this address.")
    within: Text | None = Field(None, description="Only subnets inside this prefix (10.0.0.0/8).")
    prefix: Text | None = Field(None, description="Only this exact subnet (10.1.1.0/24).")
    tenant: Text | None = None
    vrf: Text | None = None
    bridge_domain: Text | None = None
    limit: Annotated[int, Field(ge=1, le=PREVIEW_ROWS)] = PREVIEW_ROWS
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0

    @field_validator("contains_ip")
    @classmethod
    def _ip(cls, value: str | None) -> str | None:
        if value is not None:
            ipaddress.ip_address(value)
        return value

    @field_validator("within", "prefix")
    @classmethod
    def _net(cls, value: str | None) -> str | None:
        if value is not None:
            _network(value)
        return value


# -- find_aci_endpoint -------------------------------------------------------------------------


async def _find_endpoint(ctx: ToolContext, args: FindEndpointInput) -> ToolOutput:
    if (blocked := _gate(ctx)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source)
    if isinstance(sources, ToolOutput):
        return sources
    rows: list[tuple[str, Any]] = []
    errors: list[dict[str, str]] = []
    invalid = False

    async def one(source: AciSource) -> None:
        nonlocal invalid
        try:
            found = await source.endpoints.find(args.address)
        except AciValidationError:
            invalid = True  # the service rejects a malformed address before any request
            return
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        rows.extend((source.source_id, endpoint) for endpoint in found)

    await asyncio.gather(*(one(s) for s in sources))
    if invalid:
        return _BAD_ADDRESS
    if not rows and errors and len(errors) >= len(sources):
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"The ACI fabric could not be searched. {detail}", is_error=True)
    withheld: dict[str, str] = {}
    rows.sort(key=lambda r: (r[0], r[1].mac))
    endpoints = [
        {"source_id": sid, **project(ctx.sharing, endpoint, withheld)} for sid, endpoint in rows
    ]
    payload: dict[str, Any] = {"endpoints": endpoints}
    if not endpoints:
        payload["message"] = (
            f"The fabric has not learned '{args.address}'. That does not prove it does not "
            "exist: a silent or aged-out host is not in the endpoint table."
        )
    if errors:
        payload["source_errors"] = errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


# -- list_aci_endpoints ------------------------------------------------------------------------


def _in_prefix(endpoint: AciEndpoint, prefix: str | None) -> bool:
    if prefix is None:
        return True
    network = _network(prefix)
    for address in endpoint.ips:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # noqa: S112 - an address that does not parse is not in any prefix
            continue
        if ip.version == network.version and ip in network:
            return True
    return False


async def _list_endpoints(ctx: ToolContext, args: ListEndpointsInput) -> ToolOutput:
    if (blocked := _gate(ctx)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source, COST_ENDPOINT_LISTING)
    if isinstance(sources, ToolOutput):
        return sources
    rows: list[tuple[str, AciEndpoint]] = []
    errors: list[dict[str, str]] = []

    async def one(source: AciSource) -> None:
        try:
            found = await source.endpoints.list_endpoints(
                tenant=args.tenant, app_profile=args.app_profile, epg=args.epg
            )
        except AciValidationError:
            errors.append(
                {"source_id": source.source_id, "error": "A name has unsupported characters."}
            )
            return
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        rows.extend((source.source_id, e) for e in found if _in_prefix(e, args.within))

    await asyncio.gather(*(one(s) for s in sources))
    if not rows and errors and len(errors) >= len(sources):
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"The ACI fabric could not be read. {detail}", is_error=True)
    rows.sort(key=lambda r: (r[0], r[1].tenant or "", r[1].epg or "", r[1].mac))
    window = rows[args.offset : args.offset + args.limit]
    withheld: dict[str, str] = {}
    payload: dict[str, Any] = {
        "total": len(rows),
        "offset": args.offset,
        "has_more": args.offset + len(window) < len(rows),
        "endpoints": [{"source_id": sid, **project(ctx.sharing, e, withheld)} for sid, e in window],
    }
    if not rows:
        payload["message"] = (
            f"The fabric has learned no endpoint in {args.tenant}"
            + (f"/{args.app_profile}" if args.app_profile else "")
            + (f"/{args.epg}" if args.epg else "")
            + ". A configured EPG has endpoints only once a host sends traffic."
        )
    if errors:
        payload["source_errors"] = errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


# -- get_aci_endpoint_history ------------------------------------------------------------------


async def _endpoint_history(ctx: ToolContext, args: EndpointHistoryInput) -> ToolOutput:
    if (blocked := _gate(ctx)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source, COST_ENDPOINT_LISTING)
    if isinstance(sources, ToolOutput):
        return sources
    rows: list[tuple[str, Any]] = []
    errors: list[dict[str, str]] = []
    invalid = False

    async def one(source: AciSource) -> None:
        nonlocal invalid
        try:
            found = await source.endpoints.history(args.address)
        except AciValidationError:
            invalid = True  # the service rejects a malformed address before any request
            return
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        rows.extend((source.source_id, h) for h in found)

    await asyncio.gather(*(one(s) for s in sources))
    if invalid:
        return _BAD_ADDRESS
    if not rows and errors and len(errors) >= len(sources):
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"The ACI fabric could not be searched. {detail}", is_error=True)
    rows.sort(key=lambda r: (r[0], r[1].mac))
    withheld: dict[str, str] = {}
    payload: dict[str, Any] = {
        "endpoints": [{"source_id": sid, **project(ctx.sharing, h, withheld)} for sid, h in rows],
        "note": HISTORY_NOTE,
        "events_shown_per_kind": MAX_EVENTS,
    }
    if not rows:
        payload["message"] = (
            f"The fabric has not learned '{args.address}', so there is no record to date. That "
            "does not prove it never existed."
        )
    if errors:
        payload["source_errors"] = errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


# -- list_aci_subnets --------------------------------------------------------------------------


def _matches(subnet: AciSubnet, args: ListSubnetsInput) -> bool:
    if args.tenant is not None and subnet.tenant != args.tenant:
        return False
    if args.vrf is not None and subnet.vrf != args.vrf:
        return False
    if args.bridge_domain is not None and subnet.bridge_domain != args.bridge_domain:
        return False
    if not (args.contains_ip or args.within or args.prefix):
        return True
    try:
        network = _network(subnet.prefix)
    except ValueError:
        return False  # a prefix the APIC returned that does not parse never matches a filter
    if args.contains_ip is not None:
        address = ipaddress.ip_address(args.contains_ip)
        if address.version != network.version or address not in network:
            return False
    if args.within is not None:
        outer = _network(args.within)
        if outer.version != network.version or not network.subnet_of(outer):  # type: ignore[arg-type]
            return False
    if args.prefix is not None and _network(args.prefix) != network:
        return False
    return True


async def _list_subnets(ctx: ToolContext, args: ListSubnetsInput) -> ToolOutput:
    if (blocked := _gate(ctx)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source, COST_FULL_SUBNET_READ)
    if isinstance(sources, ToolOutput):
        return sources
    rows: list[tuple[str, AciSubnet]] = []
    errors: list[dict[str, str]] = []

    async def one(source: AciSource) -> None:
        try:
            subnets = await source.subnets.list_subnets()
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        rows.extend((source.source_id, s) for s in subnets if _matches(s, args))

    await asyncio.gather(*(one(s) for s in sources))
    if not rows and errors and len(errors) >= len(sources):
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"The ACI fabric could not be read. {detail}", is_error=True)
    rows.sort(key=lambda r: (r[0], r[1].tenant, r[1].prefix, r[1].bridge_domain or ""))
    page = rows[args.offset : args.offset + args.limit]
    withheld: dict[str, str] = {}
    payload: dict[str, Any] = {
        "total": len(rows),
        "offset": args.offset,
        "has_more": args.offset + len(page) < len(rows),
        "subnets": [
            {"source_id": sid, **project(ctx.sharing, subnet, withheld)} for sid, subnet in page
        ],
    }
    if errors:
        payload["source_errors"] = errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


def build_aci_lookup_tools() -> tuple[Tool, ...]:
    async def endpoint(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _find_endpoint(ctx, args)

    async def subnets(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_subnets(ctx, args)

    async def listing(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_endpoints(ctx, args)

    async def history(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _endpoint_history(ctx, args)

    return (
        Tool(
            "find_aci_endpoint",
            "Where is an IPv4 or MAC address in the Cisco ACI fabric? Returns the learned "
            "endpoint: MAC, IPs, tenant, application profile, EPG (or external EPG), encap and "
            "attachments (pod, leaf node ids, port or vPC). An empty list means the fabric has "
            "not learned it (silent or aged out), not that it does not exist; an endpoint behind "
            "a hypervisor (VMM) shows no attachment. It is the fabric's current view, not "
            "Nautobot's documentation: cross-check with Nautobot. Needs the inventory and "
            "addresses switches (checked before any request).",
            FindEndpointInput,
            endpoint,
        ),
        Tool(
            "list_aci_endpoints",
            "List the endpoints (servers, VMs, devices) the Cisco ACI fabric has learned in a "
            "tenant, an application profile or an EPG: MAC, IPs, EPG, VRF, bridge domain, encap "
            "and where each is attached (leaf and port or vPC). Narrow with within (an IP "
            "prefix); page with limit / offset (total says how many). A configured EPG lists "
            "only hosts that sent traffic; an empty list is an answer. A whole big tenant may "
            "be too many: name the profile or EPG. Needs the inventory and addresses switches.",
            ListEndpointsInput,
            listing,
        ),
        Tool(
            "get_aci_endpoint_history",
            "When did the APIC learn and last change an endpoint? For an IPv4 or MAC address: the "
            "endpoint's last change, when each of its addresses was learned, its record on each "
            "leaf (interface, first seen, last change) and the newest event and fault log lines "
            "that name it. The APIC keeps no move history, so this is the timestamps of the "
            "current records plus the logs, not a timeline of moves; say so. Needs the inventory "
            "and addresses switches; the log text needs the content switch.",
            EndpointHistoryInput,
            history,
        ),
        Tool(
            "list_aci_subnets",
            "List the gateway subnets of the Cisco ACI fabric with their tenant, VRF, bridge "
            "domain (or EPG) and scope. Use contains_ip for 'which bridge domain / VRF owns "
            "10.1.1.5', within or prefix for a range, or tenant / vrf / bridge_domain. Page with "
            "limit / offset (total says how many match). A host can be a learned endpoint "
            "(find_aci_endpoint) and also sit in a gateway subnet: 'where is this IP' needs both. "
            "Needs the inventory and addresses switches.",
            ListSubnetsInput,
            subnets,
        ),
    )
