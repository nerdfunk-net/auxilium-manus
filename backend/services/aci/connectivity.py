"""Can host A reach host B on a protocol and port? A reading of the fabric's contract policy.

Pure functions over an ``AciPolicySnapshot`` read with ``with_flow=True`` and the endpoints the
fabric learned for the two addresses. The rules follow ACI's policy model, in this order:

1. Both sides must be known (a learned endpoint, or an address inside an L3Out external-EPG
   subnet that is classified with ``import-security``). Otherwise the answer is ``unknown``.
2. An endpoint security group (ESG) or two different VRFs are not evaluated: ``unknown``.
3. A VRF that does not enforce policy permits everything; so does one EPG talking to itself
   (unless intra-EPG isolation is on); so do two preferred-group members of a VRF with the
   preferred group enabled.
4. Otherwise a contract is needed that the *destination* provides and the *source* consumes
   (directly, or through the VRF's ``vzAny``), whose scope covers both, and that has a filter
   entry for the protocol and port. No such contract is an implicit deny.
5. A taboo contract on either side can still deny a permit: the answer then is ``unknown``.

This is intent read from the APIC, not a packet trace. Not evaluated: service graphs and
policy-based redirect, route leaking between VRFs, contract interfaces, QoS and the exact
forwarding path. Return traffic of an allowed flow is allowed by the fabric.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Sequence

from models.aci_endpoint import AciEndpoint
from models.aci_flow import AciFlowContract, AciFlowLeaf, AciFlowParty, AciFlowVerdict
from models.aci_policy import AciPolicyContract, AciPolicyFilterEntry, AciVrfPolicy
from services.aci.policy_search import entry_covers, readable_epg
from services.aci.policy_service import AciPolicySnapshot

FLOW_LIMITS = (
    "This reads the contract intent of the APIC. It does not evaluate service graphs, policy-based "
    "redirect, route leaking between VRFs, contract interfaces or the real forwarding path, and "
    "it is not a packet trace. A host that is silent is not learned by the fabric."
)
MAX_PARTIES = 3
_CLASSIFIES = "import-security"
_EPG_PARTS = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)$")
_TENANT_OF = re.compile(r"^uni/tn-([^/]+)/")


def describe_entry(entry: AciPolicyFilterEntry) -> str:
    """``tcp 443``, ``udp 1000-2000`` or ``any``: a filter entry in one phrase."""
    protocol = entry.protocol or "any"
    low, high = entry.destination_port_from, entry.destination_port_to
    if low is None and high is None:
        return protocol if protocol != "any" else "any"
    if high in (None, low):
        return f"{protocol} {low}"
    return f"{protocol} {low}-{high}"


def _entries(contract: AciPolicyContract) -> list[AciPolicyFilterEntry]:
    return [e for s in contract.subjects for f in s.filters for e in f.entries]


def party_for_endpoint(address: str, endpoint: AciEndpoint) -> AciFlowParty:
    """The side of a flow that a learned endpoint stands for."""
    epg_dn = None
    if endpoint.epg and endpoint.app_profile and endpoint.tenant:
        epg_dn = f"uni/tn-{endpoint.tenant}/ap-{endpoint.app_profile}/epg-{endpoint.epg}"
    elif endpoint.external_epg and endpoint.tenant:
        out, _, instp = endpoint.external_epg.partition("/")
        epg_dn = f"uni/tn-{endpoint.tenant}/out-{out}/instP-{instp}"
    leaves = sorted({(a.pod_id, node) for a in endpoint.attachments for node in a.node_ids})
    return AciFlowParty(
        address=address,
        how="endpoint",
        epg_dn=epg_dn,
        epg_path=readable_epg(epg_dn) if epg_dn else None,
        vrf=endpoint.vrf,
        esg=endpoint.esg,
        leaves=tuple(AciFlowLeaf(pod_id=p, node_id=n) for p, n in leaves),
    )


def external_party(snapshot: AciPolicySnapshot, address: str) -> AciFlowParty:
    """The external EPG whose ``import-security`` subnet covers an address (longest prefix)."""
    ip = ipaddress.ip_address(address)
    best: tuple[int, str, str, str | None] | None = None
    for out in snapshot.l3outs.values():
        for ext in out.external_epgs:
            for subnet in ext.subnets:
                if _CLASSIFIES not in subnet.scope:
                    continue
                try:
                    network = ipaddress.ip_network(subnet.ip, strict=False)
                except ValueError:  # noqa: S112 - an unparsable subnet matches nothing
                    continue
                if network.version == ip.version and ip in network:
                    candidate = (network.prefixlen, ext.epg_dn, out.tenant, out.vrf)
                    if best is None or candidate[0] > best[0]:
                        best = candidate
    if best is None:
        return AciFlowParty(address=address, how="unknown")
    _, epg_dn, tenant, vrf = best
    return AciFlowParty(
        address=address,
        how="external_subnet",
        epg_dn=epg_dn,
        epg_path=readable_epg(epg_dn),
        vrf=f"?/{vrf}" if vrf else None,  # the tenant of an L3Out's VRF is not known here
    )


def parties(
    snapshot: AciPolicySnapshot, address: str, endpoints: Sequence[AciEndpoint]
) -> list[AciFlowParty]:
    """Every endpoint of an address as a party; else its external EPG; else an unknown party."""
    found = [party_for_endpoint(address, e) for e in endpoints[:MAX_PARTIES]]
    return found or [external_party(snapshot, address)]


def _vrf_parts(value: str | None) -> tuple[str, str] | None:
    if not value or "/" not in value:
        return None
    tenant, _, name = value.partition("/")
    return tenant, name


def _same_vrf(a: str | None, b: str | None) -> bool | None:
    """True / False when both VRFs are known, ``None`` when one is not."""
    left, right = _vrf_parts(a), _vrf_parts(b)
    if left is None or right is None:
        return None
    if left[1] != right[1]:
        return False
    return left[0] == right[0] or "?" in (left[0], right[0]) or "common" in (left[0], right[0])


def _vrf_policy(
    snapshot: AciPolicySnapshot, src: AciFlowParty, dst: AciFlowParty
) -> AciVrfPolicy | None:
    for party in (src, dst):
        parts = _vrf_parts(party.vrf)
        if parts and parts[0] != "?" and (policy := snapshot.vrfs.get(parts)) is not None:
            return policy
    named = [
        p
        for party in (src, dst)
        if (parts := _vrf_parts(party.vrf))
        for p in snapshot.vrfs.values()
        if p.name == parts[1]
    ]
    return named[0] if len({(p.tenant, p.name) for p in named}) == 1 else None


def _tenant_ap(epg_dn: str | None) -> tuple[str | None, str | None]:
    if epg_dn and (m := _EPG_PARTS.match(epg_dn)):
        return m.group(1), m.group(2)
    if epg_dn and (t := _TENANT_OF.match(epg_dn)):
        return t.group(1), None
    return None, None


def _scope_ok(contract: AciPolicyContract, src: AciFlowParty, dst: AciFlowParty) -> bool:
    """Does the contract's scope reach from the source EPG to the destination EPG?"""
    scope = contract.scope or "context"
    if scope in ("context", "global"):
        return True  # the same-VRF rule was applied before
    (s_tenant, s_ap), (d_tenant, d_ap) = _tenant_ap(src.epg_dn), _tenant_ap(dst.epg_dn)
    if scope == "tenant":
        return s_tenant is not None and s_tenant == d_tenant
    if scope == "application-profile":
        return s_ap is not None and (s_tenant, s_ap) == (d_tenant, d_ap)
    return True


def _verdict(
    src: AciFlowParty,
    dst: AciFlowParty,
    protocol: str,
    port: int | None,
    verdict: str,
    reason: str,
    explanation: str,
    contracts: Iterable[AciFlowContract] = (),
    notes: Iterable[str] = (),
) -> AciFlowVerdict:
    return AciFlowVerdict(
        source=src,
        destination=dst,
        protocol=protocol,
        port=port,
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        explanation=explanation,
        contracts=tuple(contracts),
        notes=tuple(notes),
    )


def assess_flow(
    snapshot: AciPolicySnapshot,
    src: AciFlowParty,
    dst: AciFlowParty,
    protocol: str,
    port: int | None,
) -> AciFlowVerdict:
    """The verdict for one source / destination pair (see the module doc for the rules)."""

    def done(verdict: str, reason: str, why: str, **extra: Iterable[object]) -> AciFlowVerdict:
        return _verdict(src, dst, protocol, port, verdict, reason, why, **extra)  # type: ignore[arg-type]

    for side, party in (("source", src), ("destination", dst)):
        if party.epg_dn is None:
            return done(
                "unknown",
                f"{side}_not_found",
                f"The fabric has not learned the {side} address {party.address} and no L3Out "
                "external-EPG subnet covers it, so its EPG is unknown.",
            )
        if party.esg:
            return done(
                "unknown",
                "esg_not_evaluated",
                f"The {side} is classified into the endpoint security group {party.esg}; ESG "
                "policy is not evaluated here.",
            )
    if src.epg_dn is None or dst.epg_dn is None:  # the loop above returned for these
        return done("unknown", "not_resolved", "A side of the flow could not be resolved.")
    same_vrf = _same_vrf(src.vrf, dst.vrf)
    if same_vrf is False:
        return done(
            "unknown",
            "different_vrf",
            f"The hosts are in different VRFs ({src.vrf} and {dst.vrf}). They can only talk "
            "through route leaking (a contract plus leaked subnets), which is not evaluated.",
        )
    notes: list[str] = []
    if same_vrf is None:
        notes.append("The VRF of one side is not known, so the VRF rules were checked loosely.")
    vrf = _vrf_policy(snapshot, src, dst)
    if vrf is not None and not vrf.enforced:
        return done(
            "permitted",
            "unenforced_vrf",
            f"The VRF {vrf.tenant}/{vrf.name} does not enforce policy: hosts in it talk without "
            "a contract.",
            notes=notes,
        )
    flags = snapshot.flags
    s_flags, d_flags = flags.get(src.epg_dn), flags.get(dst.epg_dn)
    if src.epg_dn == dst.epg_dn:
        if s_flags is not None and s_flags.isolated:
            return done(
                "not_permitted",
                "same_epg_isolated",
                "Both hosts are in the same EPG, but intra-EPG isolation is enforced there.",
                notes=notes,
            )
        return done(
            "permitted",
            "same_epg",
            "Both hosts are in the same EPG, which needs no contract.",
            notes=notes,
        )
    if (
        vrf is not None
        and vrf.preferred_group
        and s_flags is not None
        and d_flags is not None
        and s_flags.preferred_group
        and d_flags.preferred_group
    ):
        return done(
            "permitted",
            "preferred_group",
            "Both EPGs are members of the VRF's preferred group, which talks without contracts.",
            notes=notes,
        )

    any_provided = set(vrf.any_provided) if vrf else set()
    any_consumed = set(vrf.any_consumed) if vrf else set()
    linking: list[tuple[AciFlowContract, bool]] = []
    for contract in snapshot.contracts.values():
        ref = f"{contract.tenant}/{contract.name}"
        provided = dst.epg_dn in contract.provider_epgs or ref in any_provided
        consumed = src.epg_dn in contract.consumer_epgs or ref in any_consumed
        if provided and consumed and _scope_ok(contract, src, dst):
            shaped_contract = _contract(contract, protocol, port)
            linking.append((shaped_contract, bool(shaped_contract.matching_entries)))
    shaped = [c for c, _ in linking]
    taboo = [*(s_flags.taboo if s_flags else ()), *(d_flags.taboo if d_flags else ())]
    if any(permits for _, permits in linking):
        allowing = [
            c for c, permits in zip(shaped, (p for _, p in linking), strict=True) if permits
        ]
        why = (
            f"{dst.epg_path} provides and {src.epg_path} consumes "
            + ", ".join(f"{c.tenant}/{c.name}" for c in allowing)
            + f", which has a filter entry for {_flow_text(protocol, port)}."
        )
        if taboo:
            return done(
                "unknown",
                "taboo_not_evaluated",
                why + f" A taboo contract applies ({', '.join(sorted(set(taboo)))}) and may deny "
                "it; taboo contracts are not evaluated.",
                contracts=allowing,
                notes=notes,
            )
        return done("permitted", "contract_permits", why, contracts=allowing, notes=notes)
    if linking:
        return done(
            "not_permitted",
            "contract_wrong_port",
            f"{dst.epg_path} provides and {src.epg_path} consumes "
            + ", ".join(f"{c.tenant}/{c.name}" for c in shaped)
            + f", but no filter entry covers {_flow_text(protocol, port)}.",
            contracts=shaped,
            notes=notes,
        )
    reverse = [
        f"{c.tenant}/{c.name}"
        for c in snapshot.contracts.values()
        if src.epg_dn in c.provider_epgs and dst.epg_dn in c.consumer_epgs
    ]
    if reverse:
        notes.append(
            "A contract exists in the opposite direction ("
            + ", ".join(sorted(reverse))
            + "): the destination consumes and the source provides. Contracts are directional: "
            "the consumer opens the connection to the provider."
        )
    return done(
        "not_permitted",
        "no_contract",
        f"No contract is provided by {dst.epg_path} and consumed by {src.epg_path} (or through "
        "the VRF's vzAny), so the fabric denies it by default.",
        notes=notes,
    )


def _flow_text(protocol: str, port: int | None) -> str:
    return protocol if port is None else f"{protocol}/{port}"


def _contract(contract: AciPolicyContract, protocol: str, port: int | None) -> AciFlowContract:
    entries = _entries(contract)
    return AciFlowContract(
        tenant=contract.tenant,
        name=contract.name,
        scope=contract.scope,
        matching_entries=tuple(
            describe_entry(e) for e in entries if entry_covers(e, protocol, port)
        ),
        entries=tuple(dict.fromkeys(describe_entry(e) for e in entries)),
    )
