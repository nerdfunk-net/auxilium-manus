"""``find_host``: where is this address, from the stored client data **and** the ACI fabric.

One question, two sources of a different kind (doc/CLIENT_DATA.md, doc/AI_TOOL_CHAIN.md §48):

* the client data: stored ARP and MAC table observations of the collected devices, each row with
  its age;
* the APIC's endpoint table: the fabric's live view at the moment of the call.

The two results are not merged into one schema or one age. Each keeps its own section with its
``source`` and its kind of ``freshness``; a source that is not applicable, empty or failing is a
status of its own section, never a reason to drop the other. The tool is a composition of
``find_client`` and ``find_aci_endpoint``: both run with the permission and data checks they
always had (``client_data:read`` per call, ``sources.aci:read`` per call, the inventory and
addresses switches, the ACI rate budget). It is offered only where both readers exist.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any

from pydantic import Field

from services.aci.endpoint_service import normalize_mac
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.aci_lookup_tools import FindEndpointInput, _find_endpoint
from services.ai_assistant.tools.aci_tools import Text, _SourceInput
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.client_data_tools import (
    FindClientInput,
    _classify,
    _find_client,
)

_SHOWN = 5  # rows per source; the full lists are one call of find_client / find_aci_endpoint away

_CLIENT_FRESHNESS = (
    "stored observations from the Collect Client Data step: every row has age_seconds (and "
    "ip_age_seconds); not the live network"
)
_ACI_FRESHNESS = "live: the APIC's endpoint table at the moment of this call"
_NOT_APPLICABLE = (
    "The ACI endpoint lookup takes an IPv4 or a MAC address; an IPv6 address or a hostname is "
    "searched in the client data only."
)
_NOTE = (
    "Two sources, two kinds of answer: report each with its own age and do not average them. "
    f"Only the first {_SHOWN} rows of each are shown; find_client and find_aci_endpoint return "
    "the full lists. An empty section is not proof that the host does not exist: the client "
    "data covers only collected devices (get_client_data_coverage) and the fabric forgets "
    "silent endpoints."
)


class FindHostInput(_SourceInput):
    address: Text = Field(
        description="A MAC address in any notation, an IPv4 or IPv6 address, or a hostname. The "
        "fabric is searched for a MAC or an IPv4 address only."
    )


def _gate(ctx: ToolContext) -> ToolOutput | None:
    for data_class in (DataClass.INVENTORY, DataClass.ADDRESSES):
        if not ctx.sharing.allows(data_class):
            return ToolOutput(json.dumps(not_shared_marker(data_class)))
    return None


def _acceptable_in_aci(address: str) -> bool:
    if normalize_mac(address) is not None:
        return True
    try:
        return isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address)
    except ValueError:
        return False


def _parse(out: ToolOutput) -> dict[str, Any] | None:
    try:
        parsed = json.loads(out.content)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _error_section(source: str, freshness: str, message: str) -> dict[str, Any]:
    return {"source": source, "freshness": freshness, "status": "error", "message": message}


def _client_section(out: ToolOutput) -> dict[str, Any]:
    parsed = _parse(out)
    if out.is_error or parsed is None:
        return _error_section("client_data", _CLIENT_FRESHNESS, out.content)
    rows = parsed.get("rows", [])
    result = {
        "query": parsed.get("query"),
        "likely_location": parsed.get("likely_location"),
        "rows": rows[:_SHOWN],
        "total_rows": parsed.get("total_rows", len(rows)),
        "note": parsed.get("note"),
    }
    return {
        "source": "client_data",
        "freshness": _CLIENT_FRESHNESS,
        "status": "found" if rows else "not_seen",
        "result": result,
    }


def _aci_section(out: ToolOutput) -> dict[str, Any]:
    parsed = _parse(out)
    if out.is_error or parsed is None:
        return _error_section("aci", _ACI_FRESHNESS, out.content)
    endpoints = parsed.get("endpoints", [])
    result = {key: value for key, value in parsed.items() if key != "endpoints"}
    result["endpoints"] = endpoints[:_SHOWN]
    result["endpoints_total"] = len(endpoints)
    return {
        "source": "aci",
        "freshness": _ACI_FRESHNESS,
        "status": "found" if endpoints else "not_learned",
        "result": result,
    }


async def _find_host(ctx: ToolContext, args: FindHostInput) -> ToolOutput:
    if (blocked := _gate(ctx)) is not None:
        return blocked  # before any read: existence must not leak
    if not _classify(args.address):
        return ToolOutput(
            "Give a MAC address, an IPv4 or IPv6 address, or a hostname.", is_error=True
        )
    client_call = _find_client(ctx, FindClientInput(address=args.address))
    if _acceptable_in_aci(args.address):
        client_out, aci_out = await asyncio.gather(
            client_call,
            _find_endpoint(ctx, FindEndpointInput(address=args.address, source=args.source)),
        )
        aci = _aci_section(aci_out)
    else:
        client_out = await client_call
        aci = {
            "source": "aci",
            "freshness": _ACI_FRESHNESS,
            "status": "not_applicable",
            "message": _NOT_APPLICABLE,
        }
    client = _client_section(client_out)
    payload = {"address": args.address, "client_data": client, "aci": aci, "note": _NOTE}
    text = json.dumps(payload, default=str, indent=1)
    failed = {section["status"] for section in (client, aci)} == {"error"}
    return ToolOutput(text, is_error=failed)


def build_host_lookup_tools() -> tuple[Tool, ...]:
    async def host(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _find_host(ctx, args)

    return (
        Tool(
            "find_host",
            "Where is this host? One call for 'find the IP address X' or 'where is this MAC': it "
            "asks the stored client data (ARP and MAC tables of the collected devices, with "
            "ages) and the Cisco ACI fabric (the APIC's live endpoint table) and returns the two "
            "answers in separate sections, each with its own freshness and status (found, "
            "not_seen / not_learned, not_applicable, error). The fabric is asked for a MAC or an "
            "IPv4 address only; an IPv6 address or a hostname is client data only. Look the "
            "address up in Nautobot as well. Needs the inventory and addresses switches.",
            FindHostInput,
            host,
        ),
    )
