"""Fabric policy of a Cisco ACI fabric: EPGs, contracts, subjects and filters (read-only).

One snapshot is read per APIC with fabric-wide class queries (``GET /api/class/<Class>.json``):
``fvAEPg`` + ``fvRsBd``, the relations ``fvRsProv`` / ``fvRsCons``, the contracts ``vzBrCP`` →
``vzSubj`` → ``vzRsSubjFiltAtt`` → ``vzFilter`` entries (``vzEntry``). The names follow the
documented MIT; the DevNet sandbox answered none of the relation classes in a probe, so they
could not be checked against a live APIC. Not covered: EPG-less relations (``vzAny``), L3Out
external EPGs, contract interfaces and taboo contracts.

A relation names its contract or filter without a tenant; it resolves to the same tenant first and
then to ``common``, as the APIC does.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Protocol

from models.aci_policy import (
    AciEpgFlags,
    AciExternalEpg,
    AciExternalSubnet,
    AciL3OutInterface,
    AciL3OutNode,
    AciPolicyContract,
    AciPolicyEpg,
    AciPolicyFilter,
    AciPolicyFilterEntry,
    AciPolicyL3Out,
    AciPolicySubject,
    AciVrfPolicy,
)
from services.aci.common.coerce import text
from services.aci.common.paths import parse_path
from services.aci.credentials import AciCredentials

# A snapshot fails with ``too_many_objects`` instead of being truncated.
MAX_POLICY_ROWS = 50_000
COMMON_TENANT = "common"

_UNSET = frozenset({"", "unspecified", "unknown"})
_EPG_DN = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)$")
# An application EPG or an L3Out external EPG: the owner of a relation object.
_EPG_CHILD = re.compile(r"^(uni/tn-[^/]+/(?:ap-[^/]+/epg-[^/]+|out-[^/]+/instP-[^/]+))/")
_TENANT = re.compile(r"^uni/tn-([^/]+)/")
_OUT_DN = re.compile(r"^uni/tn-([^/]+)/out-([^/]+)$")
_OUT_CHILD = re.compile(r"^(uni/tn-([^/]+)/out-([^/]+))/")
_EXT_EPG_DN = re.compile(r"^uni/tn-([^/]+)/out-([^/]+)/instP-([^/]+)$")
_EXT_SUBNET_DN = re.compile(r"^(uni/tn-[^/]+/out-[^/]+/instP-[^/]+)/extsubnet-\[")
_NODE_TDN = re.compile(r"^topology/pod-(\d+)/node-(\d+)$")
_CONTRACT_DN = re.compile(r"^uni/tn-([^/]+)/brc-([^/]+)$")
_SUBJECT_DN = re.compile(r"^uni/tn-([^/]+)/brc-([^/]+)/subj-([^/]+)$")
_SUBJECT_CHILD = re.compile(r"^uni/tn-([^/]+)/brc-([^/]+)/subj-([^/]+)/")
_ENTRY_DN = re.compile(r"^uni/tn-([^/]+)/flt-([^/]+)/e-([^/]+)$")

_CLASSES = (
    "fvAEPg",
    "fvRsBd",
    "fvRsProv",
    "fvRsCons",
    "vzBrCP",
    "vzSubj",
    "vzRsSubjFiltAtt",
    "vzEntry",
    "l3extOut",
    "l3extRsEctx",
    "l3extInstP",
    "l3extSubnet",
    "l3extRsNodeL3OutAtt",
    "l3extRsPathL3OutAtt",
    "bgpExtP",
    "ospfExtP",
    "eigrpExtP",
)
# What the contract-flow check needs on top: VRF enforcement, vzAny, taboo relations. The EPG and
# external-EPG switches (preferred group, isolation) are attributes of rows read above.
_FLOW_CLASSES = ("fvCtx", "vzAny", "vzRsAnyToProv", "vzRsAnyToCons", "fvRsProtBy")
# Protocol of the per-L3Out protocol object (``<out>/bgpExtP`` and so on).
_PROTOCOL_CLASSES = {"bgpExtP": "bgp", "ospfExtP": "ospf", "eigrpExtP": "eigrp"}


class AciClassClient(Protocol):
    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...


def _known(value: Any) -> str | None:
    result = text(value)
    return None if result is None or result.lower() in _UNSET else result


def _dn(row: dict[str, Any]) -> str:
    return text(row.get("dn")) or ""


def _qualified(tenant: str, name: str) -> str:
    return f"{tenant}/{name}"


@dataclass(frozen=True)
class AciPolicySnapshot:
    """The policy of the whole fabric; ``for_device`` slices it for one switch."""

    epgs: dict[str, AciPolicyEpg]
    contracts: dict[tuple[str, str], AciPolicyContract]
    l3outs: dict[tuple[str, str], AciPolicyL3Out] = field(default_factory=dict)
    # Only filled by ``snapshot(with_flow=True)``: how each VRF and EPG treats contracts.
    vrfs: dict[tuple[str, str], AciVrfPolicy] = field(default_factory=dict)
    flags: dict[str, AciEpgFlags] = field(default_factory=dict)

    def for_device(
        self, epg_dns: Collection[str], pod_id: int, node_id: int
    ) -> tuple[tuple[AciPolicyEpg, ...], tuple[AciPolicyContract, ...], tuple[AciPolicyL3Out, ...]]:
        """The EPGs deployed on a switch, the L3Outs it takes part in and the contracts of both.

        An EPG the policy does not know is reported by its name parts. The contracts are those
        the deployed EPGs and the external EPGs of the switch's L3Outs provide or consume.
        """
        epgs = sorted(
            (self.epgs.get(dn) or _unknown_epg(dn) for dn in set(epg_dns)),
            key=lambda e: (e.tenant or "", e.app_profile or "", e.epg or "", e.epg_dn),
        )
        l3outs = sorted(
            (o for o in self.l3outs.values() if _on_node(o, pod_id, node_id)),
            key=lambda o: (o.tenant, o.name),
        )
        used = {ref for epg in epgs for ref in (*epg.provided, *epg.consumed)}
        used |= {
            ref
            for out in l3outs
            for ext in out.external_epgs
            for ref in (*ext.provided, *ext.consumed)
        }
        contracts = sorted(
            (c for (tenant, name), c in self.contracts.items() if _qualified(tenant, name) in used),
            key=lambda c: (c.tenant, c.name),
        )
        return tuple(epgs), tuple(contracts), tuple(l3outs)


def _on_node(out: AciPolicyL3Out, pod_id: int, node_id: int) -> bool:
    return any(n.pod_id == pod_id and n.node_id == node_id for n in out.nodes) or any(
        i.pod_id == pod_id and node_id in i.node_ids for i in out.interfaces
    )


def _unknown_epg(dn: str) -> AciPolicyEpg:
    match = _EPG_DN.match(dn)
    tenant, app_profile, epg = match.groups() if match else (None, None, None)
    return AciPolicyEpg(epg_dn=dn, tenant=tenant, app_profile=app_profile, epg=epg)


class AciPolicyService:
    """Read-only fabric policy for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciClassClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def snapshot(self, *, with_flow: bool = False) -> AciPolicySnapshot:
        """The fabric policy; ``with_flow`` adds VRF and EPG contract switches (five more reads)."""
        names = (*_CLASSES, *_FLOW_CLASSES) if with_flow else _CLASSES
        fetched = await asyncio.gather(
            *[
                self._client.query_class(self._credentials, name, max_objects=MAX_POLICY_ROWS)
                for name in names
            ]
        )
        rows: dict[str, list[dict[str, Any]]] = dict(zip(names, fetched, strict=True))
        built = _build(rows)
        if not with_flow:
            return built
        vrfs, flags = _flow_facts(rows)
        return AciPolicySnapshot(
            epgs=built.epgs, contracts=built.contracts, l3outs=built.l3outs, vrfs=vrfs, flags=flags
        )


def _resolve(tenant: str, name: str, known: Collection[tuple[str, str]]) -> tuple[str, str]:
    """The tenant of a contract or filter named without one: the same tenant, else ``common``."""
    if (tenant, name) in known:
        return tenant, name
    return (COMMON_TENANT, name) if (COMMON_TENANT, name) in known else (tenant, name)


def _relations(
    rows: dict[str, list[dict[str, Any]]], contract_keys: set[tuple[str, str]]
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
]:
    """Contracts each EPG provides / consumes, and the EPGs on each side of each contract."""
    provided: dict[str, set[str]] = defaultdict(set)
    consumed: dict[str, set[str]] = defaultdict(set)
    providers: dict[tuple[str, str], set[str]] = defaultdict(set)
    consumers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for target, side, by_contract in (
        ("fvRsProv", provided, providers),
        ("fvRsCons", consumed, consumers),
    ):
        for row in rows[target]:
            child = _EPG_CHILD.match(_dn(row))
            name = _known(row.get("tnVzBrCPName"))
            if child is None or name is None:
                continue  # an L3Out external EPG or a relation without a contract
            epg_dn = child.group(1)
            owner = _TENANT.match(epg_dn)
            key = _resolve(owner.group(1) if owner else "", name, contract_keys)
            side[epg_dn].add(_qualified(*key))
            by_contract[key].add(epg_dn)
    return provided, consumed, providers, consumers


def _subjects(
    rows: dict[str, list[dict[str, Any]]],
    filter_entries: dict[tuple[str, str], tuple[AciPolicyFilterEntry, ...]],
) -> dict[tuple[str, str], list[AciPolicySubject]]:
    """Subjects by contract, each with its filters and their entries."""
    attached: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in rows["vzRsSubjFiltAtt"]:
        child = _SUBJECT_CHILD.match(_dn(row))
        name = _known(row.get("tnVzFilterName"))
        if child is None or name is None:
            continue
        tenant, contract, subject = child.groups()
        attached[(tenant, contract, subject)].append(_resolve(tenant, name, filter_entries))

    subjects: dict[tuple[str, str], list[AciPolicySubject]] = defaultdict(list)
    for row in rows["vzSubj"]:
        match = _SUBJECT_DN.match(_dn(row))
        if match is None:
            continue
        tenant, contract, subject = match.groups()
        filters = tuple(
            AciPolicyFilter(
                name=name,
                tenant=filter_tenant,
                entries=filter_entries.get((filter_tenant, name), ()),
            )
            for filter_tenant, name in sorted(attached.get((tenant, contract, subject), []))
        )
        subjects[(tenant, contract)].append(AciPolicySubject(name=subject, filters=filters))
    return subjects


def _build(rows: dict[str, list[dict[str, Any]]]) -> AciPolicySnapshot:
    contract_keys = {
        (m.group(1), m.group(2)) for r in rows["vzBrCP"] if (m := _CONTRACT_DN.match(_dn(r)))
    }
    provided, consumed, providers, consumers = _relations(rows, contract_keys)
    bridge_domains = {
        m.group(1): name
        for r in rows["fvRsBd"]
        if (m := _EPG_CHILD.match(_dn(r))) and (name := _known(r.get("tnFvBDName")))
    }

    epgs: dict[str, AciPolicyEpg] = {}
    for row in rows["fvAEPg"]:
        dn = _dn(row)
        parts = _EPG_DN.match(dn)
        if parts is None:
            continue
        epgs[dn] = AciPolicyEpg(
            epg_dn=dn,
            tenant=parts.group(1),
            app_profile=parts.group(2),
            epg=parts.group(3),
            pc_tag=_known(row.get("pcTag")),
            bridge_domain=bridge_domains.get(dn),
            provided=tuple(sorted(provided.get(dn, ()))),
            consumed=tuple(sorted(consumed.get(dn, ()))),
        )

    subjects = _subjects(rows, _filter_entries(rows["vzEntry"]))
    contracts: dict[tuple[str, str], AciPolicyContract] = {}
    for row in rows["vzBrCP"]:
        match = _CONTRACT_DN.match(_dn(row))
        if match is None:
            continue
        key = (match.group(1), match.group(2))
        contracts[key] = AciPolicyContract(
            tenant=key[0],
            name=key[1],
            scope=_known(row.get("scope")),
            priority=_known(row.get("prio")),
            subjects=tuple(sorted(subjects.get(key, ()), key=lambda s: s.name)),
            provider_epgs=tuple(sorted(providers.get(key, ()))),
            consumer_epgs=tuple(sorted(consumers.get(key, ()))),
        )
    l3outs = _l3outs(rows, provided, consumed)
    return AciPolicySnapshot(epgs=epgs, contracts=contracts, l3outs=l3outs)


_CTX_DN = re.compile(r"^uni/tn-([^/]+)/ctx-([^/]+)$")
_ANY_DN = re.compile(r"^uni/tn-([^/]+)/ctx-([^/]+)/any$")
_ANY_REL_DN = re.compile(r"^uni/tn-([^/]+)/ctx-([^/]+)/any/")


def _flow_facts(
    rows: dict[str, list[dict[str, Any]]],
) -> tuple[dict[tuple[str, str], AciVrfPolicy], dict[str, AciEpgFlags]]:
    """VRF policies (enforcement, preferred group, vzAny contracts) and per-EPG switches."""
    contract_keys = {
        (m.group(1), m.group(2)) for r in rows["vzBrCP"] if (m := _CONTRACT_DN.match(_dn(r)))
    }
    any_state: dict[tuple[str, str], bool] = {}
    for row in rows["vzAny"]:
        if m := _ANY_DN.match(_dn(row)):
            any_state[(m.group(1), m.group(2))] = text(row.get("prefGrMemb")) == "enabled"
    relations: dict[str, dict[tuple[str, str], set[str]]] = {
        "vzRsAnyToProv": defaultdict(set),
        "vzRsAnyToCons": defaultdict(set),
    }
    for cls, by_vrf in relations.items():
        for row in rows[cls]:
            m = _ANY_REL_DN.match(_dn(row))
            name = _known(row.get("tnVzBrCPName"))
            if m is None or name is None:
                continue
            key = _resolve(m.group(1), name, contract_keys)
            by_vrf[(m.group(1), m.group(2))].add(_qualified(*key))
    vrfs: dict[tuple[str, str], AciVrfPolicy] = {}
    for row in rows["fvCtx"]:
        m = _CTX_DN.match(_dn(row))
        if m is None:
            continue
        key = (m.group(1), m.group(2))
        vrfs[key] = AciVrfPolicy(
            tenant=key[0],
            name=key[1],
            enforced=text(row.get("pcEnfPref")) != "unenforced",
            preferred_group=any_state.get(key, False),
            any_provided=tuple(sorted(relations["vzRsAnyToProv"].get(key, ()))),
            any_consumed=tuple(sorted(relations["vzRsAnyToCons"].get(key, ()))),
        )
    taboo: dict[str, set[str]] = defaultdict(set)
    for row in rows["fvRsProtBy"]:
        child = _EPG_CHILD.match(_dn(row))
        name = _known(row.get("tnVzTabooName"))
        if child is not None and name is not None:
            taboo[child.group(1)].add(name)
    flags: dict[str, AciEpgFlags] = {}
    for cls in ("fvAEPg", "l3extInstP"):
        for row in rows[cls]:
            dn = _dn(row)
            flags[dn] = AciEpgFlags(
                epg_dn=dn,
                preferred_group=text(row.get("prefGrMemb")) == "include",
                isolated=text(row.get("pcEnfPref")) == "enforced",
                taboo=tuple(sorted(taboo.get(dn, ()))),
            )
    return vrfs, flags


def _external_epgs(
    rows: dict[str, list[dict[str, Any]]],
    provided: dict[str, set[str]],
    consumed: dict[str, set[str]],
) -> dict[tuple[str, str], list[AciExternalEpg]]:
    subnets: dict[str, list[AciExternalSubnet]] = defaultdict(list)
    for row in rows["l3extSubnet"]:
        owner = _EXT_SUBNET_DN.match(_dn(row))
        ip = _known(row.get("ip"))
        if owner is None or ip is None:
            continue
        subnets[owner.group(1)].append(
            AciExternalSubnet(
                ip=ip, scope=_flags(row.get("scope")), aggregate=_flags(row.get("aggregate"))
            )
        )
    by_out: dict[tuple[str, str], list[AciExternalEpg]] = defaultdict(list)
    for row in rows["l3extInstP"]:
        dn = _dn(row)
        match = _EXT_EPG_DN.match(dn)
        if match is None:
            continue
        tenant, out, name = match.groups()
        by_out[(tenant, out)].append(
            AciExternalEpg(
                epg_dn=dn,
                name=text(row.get("name")) or name,
                pc_tag=_known(row.get("pcTag")),
                subnets=tuple(sorted(subnets.get(dn, ()), key=lambda s: s.ip)),
                provided=tuple(sorted(provided.get(dn, ()))),
                consumed=tuple(sorted(consumed.get(dn, ()))),
            )
        )
    return by_out


def _flags(value: Any) -> tuple[str, ...]:
    """A comma separated APIC flag list (``import-security,shared-rtctrl``) as a tuple."""
    return tuple(part for item in (text(value) or "").split(",") if (part := item.strip()))


def _l3out_nodes(
    rows: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], list[AciL3OutNode]]:
    by_out: dict[tuple[str, str], list[AciL3OutNode]] = defaultdict(list)
    for row in rows["l3extRsNodeL3OutAtt"]:
        owner, target = _OUT_CHILD.match(_dn(row)), _NODE_TDN.match(text(row.get("tDn")) or "")
        if owner is None or target is None:
            continue
        by_out[(owner.group(2), owner.group(3))].append(
            AciL3OutNode(
                pod_id=int(target.group(1)),
                node_id=int(target.group(2)),
                router_id=_known(row.get("rtrId")),
            )
        )
    return by_out


def _l3out_interfaces(
    rows: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], list[AciL3OutInterface]]:
    by_out: dict[tuple[str, str], list[AciL3OutInterface]] = defaultdict(list)
    for row in rows["l3extRsPathL3OutAtt"]:
        owner, path = _OUT_CHILD.match(_dn(row)), parse_path(text(row.get("tDn")))
        if owner is None or path is None:
            continue
        by_out[(owner.group(2), owner.group(3))].append(
            AciL3OutInterface(
                pod_id=path.pod_id,
                node_ids=path.node_ids,
                interface=path.interface,
                address=_known(row.get("addr")),
                type=_known(row.get("ifInstT")),
                encap=_known(row.get("encap")),
                mtu=_known(row.get("mtu")),
            )
        )
    return by_out


def _l3outs(
    rows: dict[str, list[dict[str, Any]]],
    provided: dict[str, set[str]],
    consumed: dict[str, set[str]],
) -> dict[tuple[str, str], AciPolicyL3Out]:
    vrfs = {
        (m.group(2), m.group(3)): name
        for r in rows["l3extRsEctx"]
        if (m := _OUT_CHILD.match(_dn(r))) and (name := _known(r.get("tnFvCtxName")))
    }
    protocols: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cls, protocol in _PROTOCOL_CLASSES.items():
        for row in rows[cls]:
            if m := _OUT_CHILD.match(_dn(row)):
                protocols[(m.group(2), m.group(3))].add(protocol)
    nodes, interfaces = _l3out_nodes(rows), _l3out_interfaces(rows)
    external = _external_epgs(rows, provided, consumed)

    outs: dict[tuple[str, str], AciPolicyL3Out] = {}
    for row in rows["l3extOut"]:
        match = _OUT_DN.match(_dn(row))
        if match is None:
            continue
        key = (match.group(1), match.group(2))
        outs[key] = AciPolicyL3Out(
            tenant=key[0],
            name=key[1],
            vrf=vrfs.get(key),
            protocols=tuple(sorted(protocols.get(key, ()))),
            nodes=tuple(sorted(nodes.get(key, ()), key=lambda n: (n.pod_id, n.node_id))),
            interfaces=tuple(
                sorted(interfaces.get(key, ()), key=lambda i: (i.pod_id, i.node_ids, i.interface))
            ),
            external_epgs=tuple(sorted(external.get(key, ()), key=lambda e: e.name)),
        )
    return outs


def _filter_entries(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], tuple[AciPolicyFilterEntry, ...]]:
    grouped: dict[tuple[str, str], list[AciPolicyFilterEntry]] = defaultdict(list)
    for row in rows:
        match = _ENTRY_DN.match(_dn(row))
        if match is None:
            continue
        grouped[(match.group(1), match.group(2))].append(
            AciPolicyFilterEntry(
                name=text(row.get("name")) or match.group(3),
                ether_type=_known(row.get("etherT")),
                protocol=_known(row.get("prot")),
                source_port_from=_known(row.get("sFromPort")),
                source_port_to=_known(row.get("sToPort")),
                destination_port_from=_known(row.get("dFromPort")),
                destination_port_to=_known(row.get("dToPort")),
                stateful=text(row.get("stateful")),
                apply_to_fragments=text(row.get("applyToFrag")),
                tcp_flags=_known(row.get("tcpRules")),
            )
        )
    return {
        key: tuple(sorted(entries, key=lambda e: e.name or "")) for key, entries in grouped.items()
    }
