"""ACI EPG, contract and L3Out reads for Ask the Net (doc/plans/ACI_TOOL_CHAIN.md, phase 3).

Six pure reads over one policy snapshot per source (``AciPolicyService.snapshot``), kept in a
short process cache (``PolicyCache``). The permission and the data switches are checked on every
call **before** the cache is read; the cache holds fabric data, never a user's gated view.

All names (tenant, EPG, contract, filter, VRF, L3Out) are inventory data; L3Out interface and
router addresses and external subnets are addresses. The contract answers are intent, not proof
that a flow works (``CONTRACT_LIMITS``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from models.aci_policy import AciPolicyContract, AciPolicyEpg, AciPolicyL3Out
from services.aci.policy_cache import PolicyCache
from services.aci.policy_search import (
    CONTRACT_LIMITS,
    closest_names,
    contracts_between,
    readable_epg,
    resolve_epgs,
    search_contracts,
    search_epgs,
)
from services.aci.policy_service import AciPolicySnapshot
from services.ai_assistant.aci_reader import AciSource
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.aci_fields import project
from services.ai_assistant.tools.aci_tools import (
    _SOURCE_ERRORS,
    COST_LEAF_WALK,
    Text,
    _failure_sentence,
    _finish,
    _SourceInput,
    _sources_or_error,
    redacted_error,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import PREVIEW_ROWS

# One cache for the process: the snapshot is the same for anybody who may read the source.
POLICY_CACHE = PolicyCache()
# ``include_deployed_on`` reads one leaf at a time (a few APIC requests each): bounded.
MAX_DEPLOYED_LEAVES = 50
MAX_PARALLEL_LEAVES = 4
MAX_CLOSEST = 5

Page = Annotated[int, Field(ge=1, le=PREVIEW_ROWS)]
Offset = Annotated[int, Field(ge=0, le=100_000)]


class SearchEpgsInput(_SourceInput):
    name_contains: Text | None = None
    tenant: Text | None = None
    app_profile: Text | None = None
    bridge_domain: Text | None = None
    pc_tag: Text | None = Field(None, description="The class id (pcTag) of the EPG.")
    provides: Text | None = Field(None, description="Contract it provides: 'tenant/name' or name.")
    consumes: Text | None = Field(None, description="Contract it consumes: 'tenant/name' or name.")
    limit: Page = PREVIEW_ROWS
    offset: Offset = 0


class GetEpgInput(_SourceInput):
    tenant: Text
    app_profile: Text
    epg: Text
    include_deployed_on: bool = Field(
        False,
        description="Also list the leaves that carry this EPG (one read per leaf, up to 50).",
    )


class SearchContractsInput(_SourceInput):
    name_contains: Text | None = None
    tenant: Text | None = None
    scope: Text | None = Field(None, description="Contract scope, e.g. context, tenant, global.")
    protocol: Literal["tcp", "udp", "icmp", "icmpv6", "ip"] | None = Field(
        None, description="Only contracts with a filter entry that matches this protocol."
    )
    port: Annotated[int, Field(ge=1, le=65535)] | None = Field(
        None, description="Destination port that an entry must cover (needs protocol tcp or udp)."
    )
    provided_by: Text | None = Field(
        None, description="An EPG that provides it: 'tenant/app_profile/epg' or a name."
    )
    consumed_by: Text | None = Field(
        None, description="An EPG that consumes it: 'tenant/app_profile/epg' or a name."
    )
    limit: Page = PREVIEW_ROWS
    offset: Offset = 0

    @model_validator(mode="after")
    def _port_needs_protocol(self) -> SearchContractsInput:
        if self.port is not None and self.protocol not in ("tcp", "udp"):
            raise ValueError("a port needs protocol tcp or udp")
        return self


class GetContractInput(_SourceInput):
    tenant: Text
    name: Text


class ContractsBetweenInput(_SourceInput):
    epg_a: Text = Field(description="'tenant/app_profile/epg', or an EPG name when unique.")
    epg_b: Text = Field(description="'tenant/app_profile/epg', or an EPG name when unique.")


class ListL3OutsInput(_SourceInput):
    tenant: Text | None = None
    name_contains: Text | None = None
    node: Annotated[int, Field(ge=1, le=100_000)] | None = Field(
        None, description="Only L3Outs that use this fabric node id."
    )
    limit: Annotated[int, Field(ge=1, le=PREVIEW_ROWS)] = PREVIEW_ROWS
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


# -- snapshots ---------------------------------------------------------------------------------


class _Snapshots:
    def __init__(self) -> None:
        self.items: list[tuple[str, AciPolicySnapshot, float]] = []
        self.errors: list[dict[str, str]] = []
        self.total = 0
        self.sources: dict[str, AciSource] = {}


async def _snapshots(sources: tuple[AciSource, ...]) -> _Snapshots:
    out = _Snapshots()
    out.total = len(sources)
    out.sources = {s.source_id: s for s in sources}

    async def one(source: AciSource) -> None:
        try:
            snapshot, age = await POLICY_CACHE.get(source.cache_key, source.policy.snapshot)
        except _SOURCE_ERRORS as exc:
            out.errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        out.items.append((source.source_id, snapshot, age))

    await asyncio.gather(*(one(s) for s in sources))
    out.items.sort(key=lambda i: i[0])
    return out


async def _prepare(ctx: ToolContext, only: str | None, cost: int = 1) -> _Snapshots | ToolOutput:
    """Permission and switches first, then the cache: never the other way round."""
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx, only, cost)
    if isinstance(sources, ToolOutput):
        return sources
    snaps = await _snapshots(sources)
    if not snaps.items:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in snaps.errors)
        return ToolOutput(f"The ACI policy could not be read. {detail}", is_error=True)
    return snaps


def _envelope(snaps: _Snapshots, payload: dict[str, Any]) -> dict[str, Any]:
    payload["as_of_seconds_ago"] = {sid: round(age) for sid, _, age in snaps.items}
    if snaps.errors:
        payload["source_errors"] = snaps.errors
    return payload


def _epg_row(source_id: str, epg: AciPolicyEpg) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "tenant": epg.tenant,
        "app_profile": epg.app_profile,
        "epg": epg.epg,
        "pc_tag": epg.pc_tag,
        "bridge_domain": epg.bridge_domain,
        "provided_contracts": len(epg.provided),
        "consumed_contracts": len(epg.consumed),
    }


def _contract_row(source_id: str, contract: AciPolicyContract) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "tenant": contract.tenant,
        "name": contract.name,
        "scope": contract.scope,
        "subjects": len(contract.subjects),
        "provider_epgs": len(contract.provider_epgs),
        "consumer_epgs": len(contract.consumer_epgs),
    }


def _readable_contract(contract: AciPolicyContract) -> AciPolicyContract:
    """The contract with EPG names instead of DNs (a DN is never sent)."""
    return contract.model_copy(
        update={
            "provider_epgs": tuple(readable_epg(d) for d in contract.provider_epgs),
            "consumer_epgs": tuple(readable_epg(d) for d in contract.consumer_epgs),
        }
    )


def _page(rows: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    window = rows[offset : offset + limit]
    meta = {"total": len(rows), "offset": offset, "has_more": offset + len(window) < len(rows)}
    return window, meta


# -- search_aci_epgs / get_aci_epg -------------------------------------------------------------


async def _search_epgs(ctx: ToolContext, args: SearchEpgsInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source)
    if isinstance(snaps, ToolOutput):
        return snaps
    rows = [
        _epg_row(sid, e)
        for sid, snap, _ in snaps.items
        for e in search_epgs(
            snap,
            name_contains=args.name_contains,
            tenant=args.tenant,
            app_profile=args.app_profile,
            bridge_domain=args.bridge_domain,
            pc_tag=args.pc_tag,
            provides=args.provides,
            consumes=args.consumes,
        )
    ]
    window, meta = _page(rows, args.limit, args.offset)
    return _finish(ctx, _envelope(snaps, {**meta, "epgs": window}))


async def _deployed_on(source: AciSource, epg_dn: str) -> dict[str, Any]:
    """The leaves that carry an EPG, from each leaf's own ``vlanCktEp`` rows (bounded)."""
    try:
        devices = await source.devices.search()
    except _SOURCE_ERRORS as exc:
        return {"error": _failure_sentence(exc)}
    leaves = sorted((d for d in devices if d.role == "leaf"), key=lambda d: d.node_id)
    checked, skipped = leaves[:MAX_DEPLOYED_LEAVES], max(0, len(leaves) - MAX_DEPLOYED_LEAVES)
    gate = asyncio.Semaphore(MAX_PARALLEL_LEAVES)
    carried: list[dict[str, Any]] = []
    failed = 0

    async def one(leaf: Any) -> None:
        nonlocal failed
        async with gate:
            try:
                epgs = await source.details.get_epgs(leaf.pod_id or 1, leaf.node_id)
            except _SOURCE_ERRORS:
                failed += 1
                return
        rows = [e for e in epgs if e.epg_dn == epg_dn]
        if rows:
            carried.append(
                {
                    "node_id": leaf.node_id,
                    "name": leaf.name,
                    "encaps": sorted({e.encap for e in rows if e.encap}),
                    "states": sorted({e.state for e in rows if e.state}),
                }
            )

    await asyncio.gather(*(one(leaf) for leaf in checked))
    carried.sort(key=lambda c: c["node_id"])
    out: dict[str, Any] = {"leaves": carried, "leaves_checked": len(checked) - failed}
    if failed:
        out["leaves_failed"] = failed
    if skipped:
        out["leaves_not_checked"] = skipped
    return out


async def _get_epg(ctx: ToolContext, args: GetEpgInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source, COST_LEAF_WALK if args.include_deployed_on else 1)
    if isinstance(snaps, ToolOutput):
        return snaps
    found: list[dict[str, Any]] = []
    names: list[str] = []
    carriers: list[tuple[dict[str, Any], str]] = []
    for sid, snap, _ in snaps.items:
        names += [e.epg for e in snap.epgs.values() if e.epg]
        for epg in resolve_epgs(snap, f"{args.tenant}/{args.app_profile}/{args.epg}"):
            row: dict[str, Any] = {
                "source_id": sid,
                "tenant": epg.tenant,
                "app_profile": epg.app_profile,
                "epg": epg.epg,
                "pc_tag": epg.pc_tag,
                "bridge_domain": epg.bridge_domain,
                "provided": list(epg.provided),
                "consumed": list(epg.consumed),
            }
            found.append(row)
            carriers.append((row, epg.epg_dn))
    if not found:
        return _finish(
            ctx,
            _envelope(
                snaps,
                {
                    "found": False,
                    "message": f"No EPG {args.tenant}/{args.app_profile}/{args.epg}.",
                    "closest_epg_names": closest_names(args.epg, names, MAX_CLOSEST),
                },
            ),
        )
    if args.include_deployed_on:
        for row, epg_dn in carriers:
            row["deployed_on"] = await _deployed_on(snaps.sources[row["source_id"]], epg_dn)
    return _finish(ctx, _envelope(snaps, {"found": True, "epgs": found}))


# -- search_aci_contracts / get_aci_contract ---------------------------------------------------


def _dns(snap: AciPolicySnapshot, ref: str | None) -> list[str] | None:
    return None if ref is None else [e.epg_dn for e in resolve_epgs(snap, ref)]


async def _search_contracts(ctx: ToolContext, args: SearchContractsInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source)
    if isinstance(snaps, ToolOutput):
        return snaps
    rows = [
        _contract_row(sid, c)
        for sid, snap, _ in snaps.items
        for c in search_contracts(
            snap,
            name_contains=args.name_contains,
            tenant=args.tenant,
            scope=args.scope,
            protocol=args.protocol,
            port=args.port,
            provided_by=_dns(snap, args.provided_by),
            consumed_by=_dns(snap, args.consumed_by),
        )
    ]
    window, meta = _page(rows, args.limit, args.offset)
    payload = {**meta, "contracts": window}
    if args.protocol:
        payload["note"] = (
            "Contracts with a filter entry that matches; an entry without a protocol or port "
            "means any. " + CONTRACT_LIMITS
        )
    return _finish(ctx, _envelope(snaps, payload))


async def _get_contract(ctx: ToolContext, args: GetContractInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source)
    if isinstance(snaps, ToolOutput):
        return snaps
    withheld: dict[str, str] = {}
    found: list[dict[str, Any]] = []
    names: list[str] = []
    for sid, snap, _ in snaps.items:
        names += [c.name for c in snap.contracts.values()]
        if (contract := snap.contracts.get((args.tenant, args.name))) is not None:
            found.append(
                {
                    "source_id": sid,
                    **project(ctx.sharing, _readable_contract(contract), withheld),
                }
            )
    if not found:
        return _finish(
            ctx,
            _envelope(
                snaps,
                {
                    "found": False,
                    "message": f"No contract {args.tenant}/{args.name}.",
                    "closest_contract_names": closest_names(args.name, names, MAX_CLOSEST),
                },
            ),
        )
    payload: dict[str, Any] = {"found": True, "contracts": found, "note": CONTRACT_LIMITS}
    return _finish(ctx, _envelope(snaps, payload))


# -- find_aci_contracts_between ----------------------------------------------------------------


def _unique(snap: AciPolicySnapshot, ref: str) -> tuple[AciPolicyEpg | None, str | None]:
    """The one EPG a reference names, or why there is not exactly one."""
    matches = resolve_epgs(snap, ref)
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"No EPG '{ref}'."
    listed = ", ".join(readable_epg(e.epg_dn) for e in matches)
    return None, f"'{ref}' is ambiguous ({listed}); use tenant/app_profile/epg."


async def _between(ctx: ToolContext, args: ContractsBetweenInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source)
    if isinstance(snaps, ToolOutput):
        return snaps
    results: list[dict[str, Any]] = []
    problems: list[str] = []
    withheld: dict[str, str] = {}
    for sid, snap, _ in snaps.items:
        a, why_a = _unique(snap, args.epg_a)
        b, why_b = _unique(snap, args.epg_b)
        if a is None or b is None:
            problems += [f"source '{sid}': {why}" for why in (why_a, why_b) if why]
            continue
        a_to_b, b_to_a = contracts_between(snap, a, b)

        def shape(items: list[AciPolicyContract], sid: str = sid) -> list[dict[str, Any]]:
            return [project(ctx.sharing, _readable_contract(c), withheld) for c in items]

        results.append(
            {
                "source_id": sid,
                "epg_a": readable_epg(a.epg_dn),
                "epg_b": readable_epg(b.epg_dn),
                "a_provides_b_consumes": shape(a_to_b),
                "b_provides_a_consumes": shape(b_to_a),
            }
        )
    if not results:
        return redacted_error(ctx, " ".join(problems) or "No such EPGs.")
    payload: dict[str, Any] = {"results": results, "limits": CONTRACT_LIMITS}
    if problems:
        payload["problems"] = problems
    if all(not r["a_provides_b_consumes"] and not r["b_provides_a_consumes"] for r in results):
        payload["message"] = (
            "No contract links these EPGs in either direction. Without one, traffic between "
            "EPGs is denied unless the VRF is unenforced or both are in one preferred group."
        )
    return _finish(ctx, _envelope(snaps, payload))


# -- list_aci_l3outs ---------------------------------------------------------------------------


def _uses_node(out: AciPolicyL3Out, node: int) -> bool:
    return any(n.node_id == node for n in out.nodes) or any(
        node in i.node_ids for i in out.interfaces
    )


async def _l3outs(ctx: ToolContext, args: ListL3OutsInput) -> ToolOutput:
    snaps = await _prepare(ctx, args.source)
    if isinstance(snaps, ToolOutput):
        return snaps
    withheld: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for sid, snap, _ in snaps.items:
        for out in sorted(snap.l3outs.values(), key=lambda o: (o.tenant, o.name)):
            if args.tenant is not None and out.tenant != args.tenant:
                continue
            if args.name_contains and args.name_contains.lower() not in out.name.lower():
                continue
            if args.node is not None and not _uses_node(out, args.node):
                continue
            rows.append({"source_id": sid, **project(ctx.sharing, out, withheld)})
    window, meta = _page(rows, args.limit, args.offset)
    payload: dict[str, Any] = {**meta, "l3outs": window}
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, _envelope(snaps, payload))


def build_aci_policy_tools() -> tuple[Tool, ...]:
    async def search_epgs_tool(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _search_epgs(ctx, args)

    async def get_epg(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _get_epg(ctx, args)

    async def search_contracts_tool(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _search_contracts(ctx, args)

    async def get_contract(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _get_contract(ctx, args)

    async def between(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _between(ctx, args)

    async def l3outs(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _l3outs(ctx, args)

    return (
        Tool(
            "search_aci_epgs",
            "Search the application EPGs of the Cisco ACI fabric by name, tenant, application "
            "profile, bridge domain, class id (pc_tag) or the contract they provide / consume. "
            "Rows carry tenant, profile, EPG, bridge domain and the number of contracts; page "
            "with limit / offset. Policy is read once per fabric and kept for up to two minutes "
            "(as_of_seconds_ago). Needs the inventory switch.",
            SearchEpgsInput,
            search_epgs_tool,
        ),
        Tool(
            "get_aci_epg",
            "One ACI EPG by exact tenant, application profile and name: bridge domain, class id "
            "and the contracts it provides and consumes ('tenant/name'). include_deployed_on "
            "also lists the leaves that carry it (one read per leaf, so only when asked). A miss "
            "lists the closest EPG names. Needs the inventory switch.",
            GetEpgInput,
            get_epg,
        ),
        Tool(
            "search_aci_contracts",
            "Search the contracts of the Cisco ACI fabric by name, tenant, scope, the EPG that "
            "provides or consumes them, or a filter entry that matches a protocol and "
            "destination port ('which contracts allow tcp/1433'). Rows carry tenant, name, scope "
            "and subject / provider / consumer counts; read one with get_aci_contract. This is "
            "contract intent, not proof that traffic flows. Needs the inventory switch.",
            SearchContractsInput,
            search_contracts_tool,
        ),
        Tool(
            "get_aci_contract",
            "One ACI contract by tenant and name: scope, subjects, filters and entries "
            "(protocol, ports), and the provider and consumer EPGs ('tenant/app_profile/epg'). A "
            "miss lists the closest contract names. Intent, not proof of a working flow. Needs "
            "the inventory switch.",
            GetContractInput,
            get_contract,
        ),
        Tool(
            "find_aci_contracts_between",
            "Which ACI contracts connect two EPGs? Returns the contracts the first provides and "
            "the second consumes, and the reverse, with subjects and filter entries. 'No contract' "
            "is an answer. It does not know vzAny, preferred groups, taboo contracts or VRF "
            "enforcement, so never say 'traffic is allowed' from this alone; for reachability use "
            "Batfish or a live test. EPGs are 'tenant/app_profile/epg' or a unique name. Needs "
            "the inventory switch.",
            ContractsBetweenInput,
            between,
        ),
        Tool(
            "list_aci_l3outs",
            "List the L3Outs of the Cisco ACI fabric: VRF, routing protocols, border nodes, "
            "routed interfaces and the external EPGs with their subnets and contracts. Filter by "
            "tenant, name or node id. Router ids, interface addresses and external subnets need "
            "the addresses switch; names need the inventory switch.",
            ListL3OutsInput,
            l3outs,
        ),
    )
