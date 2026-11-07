"""``check_aci_connectivity``: can host A reach host B on a protocol and port? (read-only)

The REST API has no read call that answers this. Its Visibility & Troubleshooting session
(``troubleshootSession``) is created with a write, and this integration never writes to the APIC.
So the answer is assembled from reads: the endpoints the fabric learned for the two addresses
(or the L3Out external EPG that covers an unlearned address), the VRF and EPG switches
(enforcement, preferred group, intra-EPG isolation, ``vzAny``, taboo) and the contracts. The rules
are in ``services/aci/connectivity.py``; the verdict is contract intent, never a packet trace.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from models.aci_flow import AciFlowVerdict
from services.aci.connectivity import FLOW_LIMITS, assess_flow, parties
from services.aci.policy_service import AciPolicySnapshot
from services.ai_assistant.aci_reader import AciSource
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.aci_fields import project
from services.ai_assistant.tools.aci_policy_tools import POLICY_CACHE
from services.ai_assistant.tools.aci_tools import (
    _SOURCE_ERRORS,
    Text,
    _failure_sentence,
    _finish,
    _SourceInput,
    _sources_or_error,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

# Two endpoint lookups and a policy snapshot with the flow switches (about 22 reads when cold).
COST_FLOW_CHECK = 3
MAX_VERDICTS = 9


class CheckConnectivityInput(_SourceInput):
    source_ip: Text = Field(description="IPv4 address of the host that opens the connection.")
    destination_ip: Text = Field(description="IPv4 address of the host that is connected to.")
    protocol: Literal["tcp", "udp", "icmp"] = "tcp"
    port: Annotated[int, Field(ge=1, le=65535)] | None = Field(
        None, description="Destination port (needed for tcp and udp, not for icmp)."
    )

    @field_validator("source_ip", "destination_ip")
    @classmethod
    def _ipv4(cls, value: str) -> str:
        ipaddress.IPv4Address(value)  # ValueError becomes a validation message
        return value

    @model_validator(mode="after")
    def _port_rules(self) -> CheckConnectivityInput:
        if self.protocol in ("tcp", "udp") and self.port is None:
            raise ValueError("tcp and udp need a port")
        if self.protocol == "icmp" and self.port is not None:
            raise ValueError("icmp has no port")
        return self


async def _evaluate(source: AciSource, args: CheckConnectivityInput) -> list[AciFlowVerdict]:
    async def snapshot() -> AciPolicySnapshot:
        return await source.policy.snapshot(with_flow=True)

    # The flow snapshot has more reads than the plain one, so it has its own cache key.
    (policy, _age), src_eps, dst_eps = await asyncio.gather(
        POLICY_CACHE.get(f"{source.cache_key}:flow", snapshot),
        source.endpoints.find(args.source_ip),
        source.endpoints.find(args.destination_ip),
    )
    sources = parties(policy, args.source_ip, src_eps)
    destinations = parties(policy, args.destination_ip, dst_eps)
    return [
        assess_flow(policy, s, d, args.protocol, args.port) for s in sources for d in destinations
    ][:MAX_VERDICTS]


async def _check(ctx: ToolContext, args: CheckConnectivityInput) -> ToolOutput:
    for data_class in (DataClass.INVENTORY, DataClass.ADDRESSES):
        if not ctx.sharing.allows(data_class):
            return ToolOutput(json.dumps(not_shared_marker(data_class), indent=1))
    sources = await _sources_or_error(ctx, args.source, COST_FLOW_CHECK)
    if isinstance(sources, ToolOutput):
        return sources
    results: list[tuple[str, list[AciFlowVerdict]]] = []
    errors: list[dict[str, str]] = []

    async def one(source: AciSource) -> None:
        try:
            results.append((source.source_id, await _evaluate(source, args)))
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})

    await asyncio.gather(*(one(s) for s in sources))
    if not results and errors:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"The ACI fabric could not be read. {detail}", is_error=True)
    results.sort(key=lambda r: r[0])
    withheld: dict[str, str] = {}
    payload: dict[str, Any] = {
        "question": {
            "source": args.source_ip,
            "destination": args.destination_ip,
            "protocol": args.protocol,
            "port": args.port,
        },
        "results": [
            {
                "source_id": sid,
                "verdicts": [project(ctx.sharing, v, withheld) for v in verdicts],
            }
            for sid, verdicts in results
        ],
        "limits": FLOW_LIMITS,
    }
    if errors:
        payload["source_errors"] = errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


def build_aci_flow_tools() -> tuple[Tool, ...]:
    async def check(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _check(ctx, args)

    return (
        Tool(
            "check_aci_connectivity",
            "Can a host (source IPv4) connect to another host (destination IPv4) on tcp or udp "
            "port, or icmp, in the Cisco ACI fabric? It finds the EPG and VRF of both hosts "
            "(learned endpoints, or the L3Out external EPG for an outside address) and applies "
            "the contract rules: VRF enforcement, same EPG, preferred group, vzAny, and a contract "
            "the destination provides and the source consumes with a filter entry for the port. "
            "verdict is permitted, not_permitted or unknown, with a reason, the contracts "
            "involved and what they allow (so a wrong port shows the right one). This is contract "
            "intent from the APIC, not a packet trace: it does not evaluate service graphs, "
            "policy-based redirect, route leaking, ESGs or taboo contracts (those give unknown), "
            "and a silent host is not learned. Never say 'traffic flows' from it alone; for real "
            "reachability use Batfish or a live test. If it says no ACI source is configured, tell "
            "the user. Needs the inventory and addresses switches.",
            CheckConnectivityInput,
            check,
        ),
    )
