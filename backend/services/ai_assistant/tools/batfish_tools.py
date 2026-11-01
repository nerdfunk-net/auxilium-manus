"""Batfish read tools for Ask the Net (doc/AI_TOOL_CHAIN.md §10a, phase 1).

Pure reads of the Batfish *model*: no device is contacted and nothing is written. The tools are
thin adapters (§17.1): validate the input, check the user's opt-in, ask a ``BatfishReader``,
shape the rows, and publish them as the standard envelope plus a handle (``publish_table``).
The reader (``services/ai_assistant/batfish_reader.py``) wraps ``BatfishPreviewService`` and owns
the permission, the rate limit and the source lookup.

Decisions (answered 2026-11-01):

* The model picks the network and snapshot from lists (``list_batfish_networks`` /
  ``list_batfish_snapshots``); the snapshot defaults to the newest. The model never supplies a
  host, port or path: the source is an admin-configured id, and the reader checks the network
  against what the coordinator lists.
* Data classes per tool: discovery needs the inventory opt-in, the four query tools need the
  addresses opt-in (IPs and topology). ``analyze_acl`` / ``check_reachability`` (config lines)
  will need the content opt-in when they are added.

Every value that reaches Batfish is bounded and validated here: node and interface names against
a character set (no regex or specifier syntax), IPs and prefixes with ``ipaddress``, protocols
and prefix-match types from closed lists.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.batfish_shaping import (
    DEFAULT_FACT_KEYS,
    FactKey,
    fact_keys_seen,
    shape_bgp_sessions,
    shape_facts,
    shape_interfaces,
    shape_routes,
    summarize_bgp_sessions,
    summarize_facts,
    summarize_traces,
)
from services.ai_assistant.tools.result_publish import publish_table

# Key of the ``BatfishReader`` in ``ToolContext.extras``; the surface builder puts it there.
BATFISH_READER_KEY = "batfish"
MAX_NODES = 10
MAX_SNAPSHOTS_LISTED = 10
MAX_TRACES = 10
DEFAULT_TRACES = 5


class BatfishAccessError(Exception):
    """No permission, or the source/feature is not available to this user."""


class BatfishInputError(Exception):
    """The request cannot be answered; the message is written for the model and is safe to show."""


class BatfishUnavailableError(Exception):
    """The coordinator could not be reached or failed."""


@dataclass(frozen=True)
class BatfishAnswer:
    rows: list[dict[str, Any]]
    snapshot: str
    snapshot_created: str | None = None
    # The source cut the table at its preview cap, so ``rows`` is a prefix.
    truncated: bool = False


class BatfishReader(Protocol):
    async def list_sources(self) -> list[str]: ...

    async def list_networks(self, source_id: str) -> list[str]: ...

    async def list_snapshots(self, source_id: str, network: str) -> list[dict[str, str]]: ...

    async def query(
        self,
        kind: Literal["routes", "traceroute", "bgp_sessions", "interfaces", "facts"],
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishAnswer: ...


# -- inputs -----------------------------------------------------------------------------------

NodeName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=100,
        pattern=r"(?i)^[a-z0-9][a-z0-9_.:/\-]*$",
    ),
]
VrfName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.\-]+$"
    ),
]
InterfaceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_./:\-]+$"
    ),
]
Protocol_ = Literal[
    "connected", "static", "local", "ospf", "bgp", "ibgp", "ebgp", "isis", "eigrp", "rip"
]


# Stripped on input: the existence guard and the call must see the same string.
BatfishName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(_Input):
    """Which Batfish data to read. Names come from the discovery tools."""

    network: BatfishName = Field(description="Batfish network name, from list_batfish_networks")
    snapshot: BatfishName | None = Field(
        default=None, description="Snapshot name from list_batfish_snapshots; omit for the newest"
    )
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
        description="Batfish source id; only needed when several sources are configured",
    )


class NetworksInput(_Input):
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
        description="Batfish source id; omit when there is only one",
    )


class SnapshotsInput(NetworksInput):
    network: BatfishName = Field(description="Name from list_batfish_networks")


def _ip(value: str) -> str:
    return str(ipaddress.ip_address(value.strip()))


class RoutesInput(Target):
    nodes: list[NodeName] = Field(
        default_factory=list,
        max_length=MAX_NODES,
        description="Device names; empty means every device",
    )
    prefix: str | None = Field(
        default=None,
        max_length=50,
        description="IP or prefix, e.g. '10.1.2.3' or '10.1.0.0/16'; a bare address is a /32",
    )
    prefix_match_type: Literal[
        "exact", "longest_prefix_match", "longer_prefixes", "shorter_prefixes"
    ] = Field(
        default="longest_prefix_match",
        description="How prefix is matched; longest_prefix_match = 'which route does this IP use'",
    )
    protocols: list[Protocol_] = Field(
        default_factory=list, max_length=10, description="Only these routing protocols"
    )
    vrf: VrfName | None = Field(default=None, description="Only this VRF")

    @field_validator("prefix")
    @classmethod
    def _valid_prefix(cls, value: str | None) -> str | None:
        return None if value is None else str(ipaddress.ip_network(value.strip(), strict=False))


class TracerouteInput(Target):
    node: NodeName = Field(description="Device the packet starts on")
    dst_ip: str = Field(max_length=45, description="Destination IP address, e.g. '10.1.2.3'")
    src_ip: str | None = Field(
        default=None, max_length=45, description="Source IP address; optional"
    )
    ip_protocol: Literal["tcp", "udp", "icmp"] | None = Field(
        default=None, description="Protocol; optional"
    )
    dst_port: int | None = Field(
        default=None, ge=1, le=65535, description="Destination port; needs tcp or udp"
    )
    max_traces: int = Field(
        default=DEFAULT_TRACES, ge=1, le=MAX_TRACES, description="Paths to simulate at most"
    )
    trace_format: Literal["summary", "structured"] = Field(
        default="summary",
        description="summary groups identical paths with a count; structured returns raw traces",
    )

    @field_validator("dst_ip", "src_ip")
    @classmethod
    def _valid_ip(cls, value: str | None) -> str | None:
        return None if value is None else _ip(value)

    @model_validator(mode="after")
    def _port_needs_a_port_protocol(self) -> TracerouteInput:
        if self.dst_port is not None and self.ip_protocol not in ("tcp", "udp"):
            raise ValueError("dst_port needs ip_protocol tcp or udp")
        return self


class BgpInput(Target):
    nodes: list[NodeName] = Field(
        default_factory=list,
        max_length=MAX_NODES,
        description="Device names; empty means every device",
    )
    only_problems: bool = Field(default=False, description="Hide sessions that are ESTABLISHED")


class InterfacesInput(Target):
    nodes: list[NodeName] = Field(
        default_factory=list,
        max_length=MAX_NODES,
        description="Device names; empty means every device",
    )
    interface: InterfaceName | None = Field(
        default=None, description="Interface name, e.g. 'GigabitEthernet0/1'"
    )


class FactsInput(Target):
    nodes: list[NodeName] = Field(
        default_factory=list,
        max_length=MAX_NODES,
        description="Device names; empty means every device",
    )
    facts: list[FactKey] = Field(
        default_factory=lambda: list(DEFAULT_FACT_KEYS),
        min_length=1,
        max_length=len(get_args(FactKey)),
        description=(
            "Which facts to return. Default: Hostname, Logging_Servers (syslog), NTP_Servers, "
            "DNS_Servers, TACACS_Servers, SNMP_Trap_Servers"
        ),
    )


# -- helpers ----------------------------------------------------------------------------------


def _gate(ctx: ToolContext, data_class: DataClass) -> ToolOutput | None:
    if ctx.sharing.allows(data_class):
        return None
    return ToolOutput(json.dumps(not_shared_marker(data_class)))


def _reader(ctx: ToolContext) -> BatfishReader:
    return ctx.extras[BATFISH_READER_KEY]


def _error(exc: Exception) -> ToolOutput:
    if isinstance(exc, BatfishInputError):
        return ToolOutput(str(exc), is_error=True)
    if isinstance(exc, BatfishAccessError):
        return ToolOutput("Batfish queries are not available to this user.", is_error=True)
    return ToolOutput(
        "Batfish is not reachable right now. Tell the user and try again later.", is_error=True
    )


_READER_ERRORS = (BatfishAccessError, BatfishInputError, BatfishUnavailableError)


async def _source(ctx: ToolContext, requested: str | None) -> str | ToolOutput:
    if requested:
        return requested
    try:
        sources = await _reader(ctx).list_sources()
    except _READER_ERRORS as exc:
        return _error(exc)
    if not sources:
        return ToolOutput("No Batfish source is configured.", is_error=True)
    if len(sources) > 1:
        return ToolOutput(
            f"Several Batfish sources are configured ({', '.join(sorted(sources))}); "
            "pass source_id to choose one.",
            is_error=True,
        )
    return sources[0]


def _csv(values: list[str]) -> str | None:
    return ",".join(values) if values else None


async def _list_networks(ctx: ToolContext, args: NetworksInput) -> ToolOutput:
    if (blocked := _gate(ctx, DataClass.INVENTORY)) is not None:
        return blocked
    source = await _source(ctx, args.source_id)
    if isinstance(source, ToolOutput):
        return source
    try:
        networks = await _reader(ctx).list_networks(source)
    except _READER_ERRORS as exc:
        return _error(exc)
    ctx.audit_refs.add(f"batfish:{source}")
    return ToolOutput(json.dumps({"source_id": source, "networks": sorted(networks)}, indent=1))


async def _list_snapshots(ctx: ToolContext, args: SnapshotsInput) -> ToolOutput:
    if (blocked := _gate(ctx, DataClass.INVENTORY)) is not None:
        return blocked
    source = await _source(ctx, args.source_id)
    if isinstance(source, ToolOutput):
        return source
    try:
        snapshots = await _reader(ctx).list_snapshots(source, args.network)
    except _READER_ERRORS as exc:
        return _error(exc)
    ctx.audit_refs.add(f"batfish:{source}/{args.network}")
    newest_first = sorted(
        snapshots, key=lambda s: (s.get("created", ""), s.get("name", "")), reverse=True
    )
    shown = newest_first[:MAX_SNAPSHOTS_LISTED]
    payload = {
        "source_id": source,
        "network": args.network,
        "total": len(snapshots),
        "snapshots": shown,
        "note": "Newest first. Omit 'snapshot' in a query to use the newest.",
    }
    return ToolOutput(json.dumps(payload, indent=1), truncated=len(shown) < len(snapshots))


async def _run(
    ctx: ToolContext,
    args: Target,
    kind: Literal["routes", "traceroute", "bgp_sessions", "interfaces", "facts"],
    params: dict[str, Any],
) -> tuple[str, BatfishAnswer] | ToolOutput:
    if (blocked := _gate(ctx, DataClass.ADDRESSES)) is not None:
        return blocked
    source = await _source(ctx, args.source_id)
    if isinstance(source, ToolOutput):
        return source
    ctx.audit_refs.add(f"batfish:{source}/{args.network}")
    try:
        answer = await _reader(ctx).query(kind, source, args.network, args.snapshot, params)
    except _READER_ERRORS as exc:
        return _error(exc)
    return source, answer


def _context(source: str, args: Target, answer: BatfishAnswer) -> dict[str, Any]:
    """What the answer rests on. The model must say which snapshot it used and how old it is."""
    return {
        "source_id": source,
        "network": args.network,
        "snapshot": answer.snapshot,
        "snapshot_created": answer.snapshot_created,
    }


async def _get_routes(ctx: ToolContext, args: RoutesInput) -> ToolOutput:
    params = {
        "nodes": _csv(args.nodes),
        "network_prefix": args.prefix,
        "prefix_match_type": args.prefix_match_type.upper() if args.prefix else None,
        "protocols": _csv(list(args.protocols)),
        "vrfs": args.vrf,
    }
    ran = await _run(ctx, args, "routes", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    return await publish_table(
        ctx,
        shape_routes(answer.rows),
        kind="routes",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        extra=_context(source, args, answer),
    )


async def _get_traceroute(ctx: ToolContext, args: TracerouteInput) -> ToolOutput:
    applications = [f"{args.ip_protocol}/{args.dst_port}"] if args.dst_port else None
    protocol = args.ip_protocol.upper() if args.ip_protocol and not args.dst_port else None
    params = {
        "start_node": args.node,
        "dst_ips": args.dst_ip,
        "src_ips": args.src_ip,
        "applications": applications,
        "ip_protocols": protocol,
        "max_traces": args.max_traces,
    }
    ran = await _run(ctx, args, "traceroute", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    rows, note = answer.rows, None
    if args.trace_format == "summary":
        rows, recognised = summarize_traces(answer.rows)
        if not recognised:
            note = (
                "The traces could not be summarised (unexpected shape), so the raw rows are "
                "shown. Say so and do not infer a path from them."
            )
    return await publish_table(
        ctx,
        rows,
        kind="traceroute",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra=_context(source, args, answer),
    )


async def _get_bgp(ctx: ToolContext, args: BgpInput) -> ToolOutput:
    ran = await _run(ctx, args, "bgp_sessions", {"nodes": _csv(args.nodes)})
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    extra = {
        **_context(source, args, answer),
        "status_counts": summarize_bgp_sessions(answer.rows),
        "status_counts_complete": not answer.truncated,
    }
    note = (
        "The coordinator answer was cut, so status_counts and only_problems cover only the first "
        f"{len(answer.rows)} sessions. Do not report a healthy network from this; narrow the "
        "request with nodes and ask again."
        if answer.truncated
        else None
    )
    return await publish_table(
        ctx,
        shape_bgp_sessions(answer.rows, only_problems=args.only_problems),
        kind="bgp_sessions",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra=extra,
    )


async def _get_interfaces(ctx: ToolContext, args: InterfacesInput) -> ToolOutput:
    params = {"nodes": _csv(args.nodes), "interfaces": args.interface}
    ran = await _run(ctx, args, "interfaces", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    # Descriptions are free text from the config: only with the content opt-in, and then the whole
    # table (and its handle) is content-class, so switching the opt-in off closes the handle too.
    with_description = ctx.sharing.allows(DataClass.CONTENT)
    return await publish_table(
        ctx,
        shape_interfaces(answer.rows, include_description=with_description),
        kind="interfaces",
        data_class=DataClass.CONTENT if with_description else DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        extra=_context(source, args, answer),
    )


async def _get_device_facts(ctx: ToolContext, args: FactsInput) -> ToolOutput:
    ran = await _run(ctx, args, "facts", {"nodes": _csv(args.nodes)})
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    keys = list(dict.fromkeys(args.facts))
    summary = summarize_facts(answer.rows, keys)
    extra: dict[str, Any] = {**_context(source, args, answer), "fact_summary": summary}
    note = (
        "Facts with an empty list are configured with no entries; a fact a device does not "
        "report is left out of its record."
    )
    if answer.rows and not any(entry["nodes_with_values"] for entry in summary.values()):
        extra["keys_seen"] = fact_keys_seen(answer.rows)
        note = (
            "No device reported a value for the requested facts (a fact that is not reported is "
            "not the same as 'none configured'). keys_seen lists the fact names Batfish returned; "
            "say that you could not confirm it rather than answering 'none'."
        )
    return await publish_table(
        ctx,
        shape_facts(answer.rows, keys),
        kind="facts",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra=extra,
    )


# -- registration -----------------------------------------------------------------------------

_SNAPSHOT_HINT = (
    " The answer comes from a Batfish snapshot (a model of the configs), not from the live "
    "device: always say which snapshot and how old it is (snapshot, snapshot_created)."
)

_TOOLS: tuple[tuple[str, str, type[BaseModel], Callable[..., Awaitable[ToolOutput]]], ...] = (
    (
        "list_batfish_networks",
        "List the networks (collections of snapshots) on the Batfish coordinator. Call this first "
        "to learn the 'network' name the other Batfish tools need.",
        NetworksInput,
        _list_networks,
    ),
    (
        "list_batfish_snapshots",
        "List the snapshots of one Batfish network, newest first, with their creation time. Use "
        "it to check how recent the model is or to pick an older snapshot.",
        SnapshotsInput,
        _list_snapshots,
    ),
    (
        "get_routes",
        "Routes from the Batfish model. To answer 'which route does 10.1.2.3 use on r1' pass "
        "nodes=['r1'], prefix='10.1.2.3' (longest_prefix_match is the default). Large results "
        "return a preview and a handle for query_result / fetch_slice." + _SNAPSHOT_HINT,
        RoutesInput,
        _get_routes,
    ),
    (
        "get_traceroute",
        "Simulate where a packet goes: the hop-by-hop path from a device to a destination IP, "
        "with its disposition (ACCEPTED, NO_ROUTE, DENIED_IN, DENIED_OUT, NEIGHBOR_UNREACHABLE, "
        "LOOP, ...). Identical paths are grouped with a count. This is a model, not a live ping."
        + _SNAPSHOT_HINT,
        TracerouteInput,
        _get_traceroute,
    ),
    (
        "get_bgp_session_status",
        "BGP sessions and whether they are established, from the Batfish model, with counts per "
        "status. Use only_problems=true to list just the sessions that are not ESTABLISHED."
        + _SNAPSHOT_HINT,
        BgpInput,
        _get_bgp,
    ),
    (
        "get_interface_properties",
        "Interface settings from the configs (address, VLAN, MTU, filters, active state), one "
        "record per interface. Restrict with nodes and interface to keep it small."
        + _SNAPSHOT_HINT,
        InterfacesInput,
        _get_interfaces,
    ),
    (
        "get_device_facts",
        "Facts Batfish extracted from the configs: management servers (Logging_Servers = syslog, "
        "NTP_Servers, DNS_Servers, TACACS_Servers, SNMP_Trap_Servers), hostname, domain name, "
        "config format, VRFs and zones. Use it for 'is syslog/NTP/DNS configured on ...' and "
        "'which devices have no ...'. Check the fact_summary (devices with a value / devices "
        "asked) first. Key material and large structures are not available." + _SNAPSHOT_HINT,
        FactsInput,
        _get_device_facts,
    ),
)


def build_batfish_tools() -> list[Tool]:
    return [Tool(name, description, model, handler) for name, description, model, handler in _TOOLS]
