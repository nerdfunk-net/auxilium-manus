"""Pure searches over an ``AciPolicySnapshot`` (no I/O): EPGs, contracts, contracts between EPGs.

Used by the Ask the Net policy tools. Everything here is a function of the snapshot, so it is
cheap to test. The contract logic is *intent*: it reads the contract objects and their provider /
consumer relations and knows nothing of ``vzAny``, preferred groups, taboo contracts, contract
interfaces or VRF enforcement (``CONTRACT_LIMITS`` says so to the caller).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from models.aci_policy import AciPolicyContract, AciPolicyEpg, AciPolicyFilterEntry
from services.aci.policy_service import AciPolicySnapshot

CONTRACT_LIMITS = (
    "This is the contract intent read from the APIC. It does not know vzAny, preferred groups, "
    "taboo contracts, contract interfaces or whether the VRF enforces policy, so it cannot prove "
    "that traffic is allowed or denied."
)

_EPG_DN = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)$")
_EXT_DN = re.compile(r"^uni/tn-([^/]+)/out-([^/]+)/instP-([^/]+)$")
# The APIC writes some well-known TCP/UDP ports by name in a filter entry.
_PORT_NAMES = {
    "ftpData": 20,
    "smtp": 25,
    "dns": 53,
    "http": 80,
    "pop3": 110,
    "https": 443,
    "rtsp": 554,
}
_IP_ETHER_TYPES = {None, "ip", "ipv4", "ipv6"}


def readable_epg(dn: str) -> str:
    """``tenant/app_profile/epg`` (``tenant/l3out/ext-epg (external)`` for an external EPG)."""
    if m := _EPG_DN.match(dn):
        return "/".join(m.groups())
    if m := _EXT_DN.match(dn):
        return "/".join(m.groups()) + " (external)"
    return dn


def _contains(text: str | None, needle: str | None) -> bool:
    return needle is None or needle.lower() in (text or "").lower()


def _refers_to(ref: str, wanted: str) -> bool:
    """A contract reference (``tenant/name``) matches ``tenant/name`` or the bare name."""
    return ref == wanted or ref.split("/", 1)[-1] == wanted


def search_epgs(
    snapshot: AciPolicySnapshot,
    *,
    name_contains: str | None = None,
    tenant: str | None = None,
    app_profile: str | None = None,
    bridge_domain: str | None = None,
    pc_tag: str | None = None,
    provides: str | None = None,
    consumes: str | None = None,
) -> list[AciPolicyEpg]:
    rows = [
        e
        for e in snapshot.epgs.values()
        if _contains(e.epg, name_contains)
        and (tenant is None or e.tenant == tenant)
        and (app_profile is None or e.app_profile == app_profile)
        and (bridge_domain is None or e.bridge_domain == bridge_domain)
        and (pc_tag is None or e.pc_tag == pc_tag)
        and (provides is None or any(_refers_to(r, provides) for r in e.provided))
        and (consumes is None or any(_refers_to(r, consumes) for r in e.consumed))
    ]
    return sorted(rows, key=lambda e: (e.tenant or "", e.app_profile or "", e.epg or ""))


def resolve_epgs(snapshot: AciPolicySnapshot, ref: str) -> list[AciPolicyEpg]:
    """``tenant/app_profile/epg`` resolves exactly; a bare name to every EPG of that name."""
    parts = ref.split("/")
    if len(parts) == 3:
        return [
            e
            for e in snapshot.epgs.values()
            if (e.tenant, e.app_profile, e.epg) == (parts[0], parts[1], parts[2])
        ]
    return sorted(
        (e for e in snapshot.epgs.values() if e.epg == ref),
        key=lambda e: (e.tenant or "", e.app_profile or ""),
    )


def closest_names(wanted: str, names: Iterable[str], limit: int = 5) -> list[str]:
    """The names nearest to ``wanted`` (for a "did you mean" answer), best first."""
    unique = sorted(set(names))
    return (
        difflib.get_close_matches(wanted, unique, n=limit, cutoff=0.5)
        or [n for n in unique if wanted.lower() in n.lower()][:limit]
    )


def port_number(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    return _PORT_NAMES.get(value)


def entry_covers(entry: AciPolicyFilterEntry, protocol: str, port: int | None) -> bool:
    """Does a filter entry match ``protocol`` (and destination ``port``)?

    An unset protocol or port in the entry means "any". A named port the table above does not
    know does not match (better a miss than a wrong yes).
    """
    if entry.ether_type not in _IP_ETHER_TYPES:
        return False
    if entry.protocol not in (None, protocol):
        return False
    if port is None:
        return True
    if entry.protocol is None:
        return True
    low, high = entry.destination_port_from, entry.destination_port_to
    if low is None and high is None:
        return True
    lo, hi = port_number(low), port_number(high if high is not None else low)
    return lo is not None and hi is not None and lo <= port <= hi


def _allows(contract: AciPolicyContract, protocol: str, port: int | None) -> bool:
    return any(
        entry_covers(entry, protocol, port)
        for subject in contract.subjects
        for flt in subject.filters
        for entry in flt.entries
    )


def search_contracts(
    snapshot: AciPolicySnapshot,
    *,
    name_contains: str | None = None,
    tenant: str | None = None,
    scope: str | None = None,
    protocol: str | None = None,
    port: int | None = None,
    provided_by: Iterable[str] | None = None,
    consumed_by: Iterable[str] | None = None,
) -> list[AciPolicyContract]:
    """``provided_by`` / ``consumed_by`` are EPG DNs (any one of them is enough)."""
    providers = set(provided_by) if provided_by is not None else None
    consumers = set(consumed_by) if consumed_by is not None else None
    rows = [
        c
        for c in snapshot.contracts.values()
        if _contains(c.name, name_contains)
        and (tenant is None or c.tenant == tenant)
        and (scope is None or c.scope == scope)
        and (protocol is None or _allows(c, protocol, port))
        and (providers is None or providers & set(c.provider_epgs))
        and (consumers is None or consumers & set(c.consumer_epgs))
    ]
    return sorted(rows, key=lambda c: (c.tenant, c.name))


def contracts_between(
    snapshot: AciPolicySnapshot, epg_a: AciPolicyEpg, epg_b: AciPolicyEpg
) -> tuple[list[AciPolicyContract], list[AciPolicyContract]]:
    """(contracts A provides and B consumes, contracts B provides and A consumes)."""

    def between(provider: AciPolicyEpg, consumer: AciPolicyEpg) -> list[AciPolicyContract]:
        return sorted(
            (
                c
                for c in snapshot.contracts.values()
                if provider.epg_dn in c.provider_epgs and consumer.epg_dn in c.consumer_epgs
            ),
            key=lambda c: (c.tenant, c.name),
        )

    return between(epg_a, epg_b), between(epg_b, epg_a)
