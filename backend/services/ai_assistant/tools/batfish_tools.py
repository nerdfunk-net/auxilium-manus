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
from dataclasses import dataclass, field
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
    InterfaceStatus,
    ParseSection,
    fact_keys_seen,
    filter_interfaces,
    shape_bgp_sessions,
    shape_facts,
    shape_filter_comparison,
    shape_filter_results,
    shape_interfaces,
    shape_parse_issues,
    shape_routes,
    summarize_bgp_sessions,
    summarize_differential_traces,
    summarize_facts,
    summarize_interfaces,
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


QueryKind = Literal[
    "routes",
    "traceroute",
    "bgp_sessions",
    "interfaces",
    "facts",
    "acl",
    "reachability",
    "compare_filters",
    "differential_reachability",
]


@dataclass(frozen=True)
class BatfishAnswer:
    rows: list[dict[str, Any]]
    snapshot: str
    snapshot_created: str | None = None
    # Only for the differential kinds: the snapshot ``snapshot`` was compared with.
    reference_snapshot: str | None = None
    reference_created: str | None = None
    # The source cut the table at its preview cap, so ``rows`` is a prefix.
    truncated: bool = False
    # Device names the reader rewrote to Batfish node names (asked -> used), for example
    # ``LAB.local.zz`` -> ``lab``. Empty when every name already was a node name.
    nodes_resolved: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotDiagnostics:
    """What Batfish reported while reading a snapshot's configs (three answers, raw rows)."""

    snapshot: str
    snapshot_created: str | None
    file_status: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    # Section name -> why it has no rows (the question failed); the other sections still answer.
    unavailable: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    # Sections whose rows were cut at the preview cap: their counts are lower bounds.
    truncated_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeListing:
    """The node (device) names of one snapshot, as Batfish spells them."""

    snapshot: str
    snapshot_created: str | None
    names: tuple[str, ...]


class BatfishReader(Protocol):
    async def list_sources(self) -> list[str]: ...

    async def list_networks(self, source_id: str) -> list[str]: ...

    async def list_snapshots(self, source_id: str, network: str) -> list[dict[str, str]]: ...

    async def query(
        self,
        kind: QueryKind,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishAnswer: ...

    async def snapshot_diagnostics(
        self, source_id: str, network: str, snapshot: str | None
    ) -> SnapshotDiagnostics: ...

    async def node_names(
        self, source_id: str, network: str, snapshot: str | None
    ) -> NodeListing: ...


# -- inputs -----------------------------------------------------------------------------------

NodeName = Annotated[
    str,
    StringConstraints(
        # Not lower-cased here: the reader matches the name against the snapshot's nodes and
        # reports the rewrite (``nodes_resolved``) with the user's own spelling.
        strip_whitespace=True,
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
    status: InterfaceStatus = Field(
        default="all",
        description=(
            "Only interfaces in this state: active, inactive, admin_down (shut down), or "
            "inactive_but_admin_up (configured up, yet Batfish treats it as inactive, usually a "
            "missing dependency such as a parent interface or port-channel member)"
        ),
    )


FilterName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        # Must not start with "/" (a regex specifier in Batfish) and has no comma or space.
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]*$",
    ),
]


class _FlowInput(Target):
    """The flow fields the ACL and reachability tools share."""

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

    @field_validator("dst_ip", "src_ip")
    @classmethod
    def _valid_ip(cls, value: str | None) -> str | None:
        return None if value is None else _ip(value)

    @model_validator(mode="after")
    def _port_needs_a_port_protocol(self) -> _FlowInput:
        if self.dst_port is not None and self.ip_protocol not in ("tcp", "udp"):
            raise ValueError("dst_port needs ip_protocol tcp or udp")
        return self


class AclInput(_FlowInput):
    node: NodeName = Field(description="Device that holds the filter")
    filter_name: FilterName = Field(
        description="Exact name of the access list / filter on that device"
    )


class ReachabilityInput(_FlowInput):
    node: NodeName = Field(description="Device the packet starts on")
    end_node: NodeName | None = Field(default=None, description="Device it should reach; optional")
    ignore_filters: bool = Field(
        default=False,
        description="Ignore ACLs: compare with and without to see whether a filter is the cause",
    )
    max_traces: int = Field(
        default=DEFAULT_TRACES, ge=1, le=MAX_TRACES, description="Paths to return at most"
    )


ReferenceSnapshotName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_REFERENCE_DESCRIPTION = (
    "The snapshot to compare against: the older state. 'snapshot' (omit for the newest) is the "
    "newer state. Name from list_batfish_snapshots; it must differ from 'snapshot'"
)


class CompareFiltersInput(Target):
    reference_snapshot: ReferenceSnapshotName = Field(description=_REFERENCE_DESCRIPTION)
    nodes: list[NodeName] = Field(
        default_factory=list,
        max_length=MAX_NODES,
        description="Device names; empty means every device",
    )
    filters: FilterName | None = Field(
        default=None, description="Exact filter / ACL name; omit for every filter"
    )


class DifferentialReachabilityInput(ReachabilityInput):
    reference_snapshot: ReferenceSnapshotName = Field(description=_REFERENCE_DESCRIPTION)
    # Unlike the other flow tools the destination is optional: "what changed from this device"
    # is a question about every destination, which the header space of the question covers.
    dst_ip: str | None = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default=None,
        max_length=45,
        description="Destination IP address; omit to look at every destination",
    )


def _flow_params(args: _FlowInput | TracerouteInput) -> tuple[list[str] | None, str | None]:
    """Batfish ``applications`` (protocol and port) and ``ipProtocols`` for the flow."""
    applications = [f"{args.ip_protocol}/{args.dst_port}"] if args.dst_port else None
    protocol = args.ip_protocol.upper() if args.ip_protocol and not args.dst_port else None
    return applications, protocol


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


class ParseIssuesInput(Target):
    section: ParseSection = Field(
        default="all",
        description=(
            "files = config files that did not parse cleanly, warnings = lines the parser did "
            "not understand, issues = problems found while building the model; all = the three"
        ),
    )
    include_passed: bool = Field(
        default=False, description="Also list the files that parsed without a problem"
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
    kind: QueryKind,
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
    context: dict[str, Any] = {
        "source_id": source,
        "network": args.network,
        "snapshot": answer.snapshot,
        "snapshot_created": answer.snapshot_created,
    }
    if answer.nodes_resolved:
        # The rows use the Batfish names; this says which device the user's name meant.
        context["nodes_resolved"] = dict(answer.nodes_resolved)
    return context


def _differential_context(source: str, args: Target, answer: BatfishAnswer) -> dict[str, Any]:
    """Both snapshots a comparison rests on, with their ages."""
    return {
        **_context(source, args, answer),
        "reference_snapshot": answer.reference_snapshot,
        "reference_snapshot_created": answer.reference_created,
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


def _summarised_traces(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Trace rows condensed to paths; the raw rows and a note when the shape is not understood."""
    summary, recognised = summarize_traces(rows)
    if recognised:
        return summary, None
    return rows, (
        "The traces could not be summarised (unexpected shape), so the raw rows are shown. "
        "Say so and do not infer a path from them."
    )


async def _get_traceroute(ctx: ToolContext, args: TracerouteInput) -> ToolOutput:
    applications, protocol = _flow_params(args)
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
    rows, note = (
        _summarised_traces(answer.rows) if args.trace_format == "summary" else (answer.rows, None)
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
    # The summary counts every interface; the status filter only narrows the rows listed. A
    # device with hundreds of ports is answered from the summary and the filter, not by paging.
    selected = filter_interfaces(answer.rows, args.status)
    note = (
        None
        if args.status == "all"
        else f"Only '{args.status}' interfaces: {len(selected)} of {len(answer.rows)}."
    )
    # Descriptions are free text from the config: only with the content opt-in, and then the whole
    # table (and its handle) is content-class, so switching the opt-in off closes the handle too.
    with_description = ctx.sharing.allows(DataClass.CONTENT)
    return await publish_table(
        ctx,
        shape_interfaces(selected, include_description=with_description),
        kind="interfaces",
        data_class=DataClass.CONTENT if with_description else DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra={
            **_context(source, args, answer),
            "summary": summarize_interfaces(answer.rows),
            "summary_complete": not answer.truncated,
        },
    )


async def _analyze_acl(ctx: ToolContext, args: AclInput) -> ToolOutput:
    applications, protocol = _flow_params(args)
    params = {
        "node": args.node,
        "filter_name": args.filter_name,
        "dst_ips": args.dst_ip,
        "src_ips": args.src_ip,
        "applications": applications,
        "ip_protocols": protocol,
    }
    ran = await _run(ctx, args, "acl", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    # The matching line is config text: only with the content opt-in, and then the whole table
    # (and its handle) is content-class, like interface descriptions.
    with_line = ctx.sharing.allows(DataClass.CONTENT)
    note = (
        None
        if with_line
        else (
            "The matching ACL line is not shown: the user has not allowed config content to be "
            "shared. The verdict (Action) is still valid."
        )
    )
    return await publish_table(
        ctx,
        shape_filter_results(answer.rows, include_line=with_line),
        kind="acl",
        data_class=DataClass.CONTENT if with_line else DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra=_context(source, args, answer),
    )


async def _check_reachability(ctx: ToolContext, args: ReachabilityInput) -> ToolOutput:
    applications, protocol = _flow_params(args)
    params = {
        "start_node": args.node,
        "end_node": args.end_node,
        "dst_ips": args.dst_ip,
        "src_ips": args.src_ip,
        "applications": applications,
        "ip_protocols": protocol,
        "max_traces": args.max_traces,
        "ignore_filters": args.ignore_filters,
    }
    ran = await _run(ctx, args, "reachability", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    rows, note = _summarised_traces(answer.rows)
    reachable = bool(answer.rows)
    if not reachable:
        note = (
            "No flow matching this description succeeds in the model. Use get_traceroute to see "
            "where the packet stops, and try ignore_filters=true to test whether a filter is the "
            "cause."
        )
    return await publish_table(
        ctx,
        rows,
        kind="reachability",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra={**_context(source, args, answer), "reachable": reachable},
    )


def _filter_comparison_note(rows: list[dict[str, Any]], *, with_lines: bool) -> str:
    if not rows:
        return (
            "No differing filter line was returned. This does not prove the ACLs are the same: a "
            "filter name that matches nothing, and a filter that exists in only one snapshot, "
            "also return nothing. If a filter name was given, confirm it exists "
            "(get_interface_properties lists Incoming_Filter_Name / Outgoing_Filter_Name) before "
            "saying nothing changed."
        )
    parts = [
        "Reference_Line_Action is derived: compareFilters lists only lines whose actions differ, "
        "so it is the opposite of Line_Action."
    ]
    if any(row.get("Reference_Line_Index") == "End of ACL" for row in rows):
        parts.append(
            "Reference_Line_Index 'End of ACL' means no line of the reference ACL matched the "
            "flow: its implicit deny at the end applied."
        )
    if not with_lines:
        parts.append(
            "The filter lines are not shown: the user has not allowed config content to be shared."
        )
    return " ".join(parts)


async def _compare_filters(ctx: ToolContext, args: CompareFiltersInput) -> ToolOutput:
    params = {
        "reference_snapshot": args.reference_snapshot,
        "nodes": _csv(args.nodes),
        "filters": args.filters,
    }
    ran = await _run(ctx, args, "compare_filters", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    # The filter lines are config text: only with the content opt-in, and then the whole table
    # (and its handle) is content-class, like analyze_acl.
    with_lines = ctx.sharing.allows(DataClass.CONTENT)
    differences = bool(answer.rows)
    note = _filter_comparison_note(answer.rows, with_lines=with_lines)
    return await publish_table(
        ctx,
        shape_filter_comparison(answer.rows, include_lines=with_lines),
        kind="compare_filters",
        data_class=DataClass.CONTENT if with_lines else DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra={**_differential_context(source, args, answer), "differences_found": differences},
    )


async def _differential_reachability(
    ctx: ToolContext, args: DifferentialReachabilityInput
) -> ToolOutput:
    applications, protocol = _flow_params(args)
    params = {
        "reference_snapshot": args.reference_snapshot,
        "start_node": args.node,
        "end_node": args.end_node,
        "dst_ips": args.dst_ip,
        "src_ips": args.src_ip,
        "applications": applications,
        "ip_protocols": protocol,
        "max_traces": args.max_traces,
        "ignore_filters": args.ignore_filters,
    }
    ran = await _run(ctx, args, "differential_reachability", params)
    if isinstance(ran, ToolOutput):
        return ran
    source, answer = ran
    differences = bool(answer.rows)
    rows, note = answer.rows, None
    destination = args.dst_ip or "any destination"
    _scope = (
        f"Only flows from {args.node} to {destination} were examined, not the rest of the network."
    )
    if differences:
        rows, recognised = summarize_differential_traces(answer.rows)
        if not recognised:
            rows, note = (
                answer.rows,
                (
                    "The traces could not be summarised (unexpected shape), so the raw rows are "
                    "shown. Say so and do not infer a path from them."
                ),
            )
    else:
        note = (
            "No flow was found that succeeds in only one snapshot. That includes a flow that "
            "fails in both, so this does not show that the traffic works: confirm with "
            "check_reachability in each snapshot before saying it works. " + _scope
        )
    return await publish_table(
        ctx,
        rows,
        kind="differential_reachability",
        data_class=DataClass.ADDRESSES,
        source_truncated=answer.truncated,
        note=note,
        extra={
            **_differential_context(source, args, answer),
            "differences_found": differences,
            "examined": {"from": args.node, "to": args.dst_ip},
        },
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


_NO_PARSE_PROBLEMS = (
    "No parse problems reported: every file parsed and Batfish raised no warnings or issues. "
    "This does not explain why an interface is inactive; check Active and the VLAN / "
    "port-channel settings with get_interface_properties."
)
_TEXT_HIDDEN = (
    "Config lines and issue details are not shown: the user has not allowed config content to "
    "be shared. File names, statuses, line numbers and counts are."
)


def _parse_issues_note(
    diagnostics: SnapshotDiagnostics, rows: list[dict[str, Any]], *, with_text: bool
) -> str | None:
    parts = []
    if diagnostics.truncated_sections:
        cut = ", ".join(diagnostics.truncated_sections)
        parts.append(
            f"The answer for {cut} was cut at the preview row cap: its counts and groups are at "
            "least these values, and messages that only occur later are missing."
        )
    if not rows and not diagnostics.unavailable:
        parts.append(_NO_PARSE_PROBLEMS)
    if diagnostics.unavailable:
        names = ", ".join(sorted(diagnostics.unavailable))
        parts.append(
            f"Batfish could not answer for: {names}. Those sections are missing, not empty."
        )
    if not with_text:
        parts.append(_TEXT_HIDDEN)
    return " ".join(parts) or None


async def _get_snapshot_parse_issues(ctx: ToolContext, args: ParseIssuesInput) -> ToolOutput:
    if (blocked := _gate(ctx, DataClass.ADDRESSES)) is not None:
        return blocked
    source = await _source(ctx, args.source_id)
    if isinstance(source, ToolOutput):
        return source
    ctx.audit_refs.add(f"batfish:{source}/{args.network}")
    try:
        diagnostics = await _reader(ctx).snapshot_diagnostics(source, args.network, args.snapshot)
    except _READER_ERRORS as exc:
        return _error(exc)
    # Warning lines and issue details quote the config: only with the content opt-in, and then
    # the whole table (and its handle) is content-class, like interface descriptions.
    with_text = ctx.sharing.allows(DataClass.CONTENT)
    rows, summary = shape_parse_issues(
        file_status=diagnostics.file_status,
        warnings=diagnostics.warnings,
        issues=diagnostics.issues,
        section=args.section,
        include_passed=args.include_passed,
        include_text=with_text,
    )
    extra: dict[str, Any] = {
        "source_id": source,
        "network": args.network,
        "snapshot": diagnostics.snapshot,
        "snapshot_created": diagnostics.snapshot_created,
        "summary": summary,
        # The counts and warning groups are taken from rows cut at the preview cap.
        "summary_complete": not diagnostics.truncated_sections,
    }
    if diagnostics.truncated_sections:
        extra["summary_cut_sections"] = list(diagnostics.truncated_sections)
    if diagnostics.unavailable:
        extra["unavailable_sections"] = sorted(diagnostics.unavailable)
    return await publish_table(
        ctx,
        rows,
        kind="parse_issues",
        data_class=DataClass.CONTENT if with_text else DataClass.ADDRESSES,
        source_truncated=diagnostics.truncated,
        note=_parse_issues_note(diagnostics, rows, with_text=with_text),
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
        "record per interface, plus a summary over every interface (total, active, inactive, "
        "shut down, inactive although configured up, switchport modes). Only 20 records are "
        "shown at once: for a device with many interfaces answer from the summary, narrow with "
        "status (for example inactive_but_admin_up to find interfaces Batfish deactivated), "
        "nodes or interface, and page the rest with query_result." + _SNAPSHOT_HINT,
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
    (
        "analyze_acl",
        "Test one flow against one named ACL / filter on a device: PERMIT or DENY, and (when the "
        "user allows config content) the matching line. Use it after get_traceroute reports "
        "DENIED_IN or DENIED_OUT, with the filter name from get_interface_properties "
        "(Incoming_Filter_Name / Outgoing_Filter_Name)." + _SNAPSHOT_HINT,
        AclInput,
        _analyze_acl,
    ),
    (
        "check_reachability",
        "Whether traffic matching a description can get from a device to a destination (or to "
        "end_node) in the model, with the paths found. reachable=false means no matching flow "
        "succeeds. Run it with and without ignore_filters to tell a filter problem from a "
        "routing problem." + _SNAPSHOT_HINT,
        ReachabilityInput,
        _check_reachability,
    ),
    (
        "compare_filters",
        "Compare the ACLs / filters of two snapshots (same-named filters): the lines that treat a "
        "flow differently, with the line numbers in both snapshots and the action of the newer "
        "line (the older action is the opposite, shown as the derived Reference_Line_Action). "
        "Use it after a change, or to find why a flow was permitted before and is denied now. "
        "'reference_snapshot' is the older state, 'snapshot' (default newest) the newer. "
        "Filters present in only one snapshot are not compared; an empty answer does not prove "
        "the ACLs are the same." + _SNAPSHOT_HINT,
        CompareFiltersInput,
        _compare_filters,
    ),
    (
        "differential_reachability",
        "Flows whose outcome differs between two snapshots: example flows that succeed in one but "
        "not the other, with the dispositions and paths on each side (in_snapshot = the newer "
        "'snapshot', in_reference = the older 'reference_snapshot'). Constrain it with node, "
        "end_node, dst_ip (optional) and protocol/port. No rows means no flow succeeds in only one "
        "snapshot; it does not show that the traffic works (it may fail in both), so confirm "
        "with check_reachability." + _SNAPSHOT_HINT,
        DifferentialReachabilityInput,
        _differential_reachability,
    ),
    (
        "get_snapshot_parse_issues",
        "What Batfish reported while reading the snapshot's configs: files that failed to parse "
        "or parsed only partly, lines the parser did not recognise (grouped, with line numbers) "
        "and problems found while building the model. Use it for 'show me the parsing errors / "
        "parser output of snapshot X', and as a first lead when many interfaces are inactive "
        "or devices are missing. Batfish does not always report the reason an interface is "
        "inactive here: if nothing relevant shows, say so and check get_interface_properties "
        "(Active)." + _SNAPSHOT_HINT,
        ParseIssuesInput,
        _get_snapshot_parse_issues,
    ),
)


def build_batfish_tools() -> list[Tool]:
    return [Tool(name, description, model, handler) for name, description, model, handler in _TOOLS]
