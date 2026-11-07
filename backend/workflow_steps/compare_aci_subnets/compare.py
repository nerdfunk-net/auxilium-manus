"""Compare ACI gateway subnets with Nautobot prefixes (pure; produces a report, changes nothing).

An ACI subnet and a Nautobot prefix are the same when the network and the namespace agree. The
namespace is one fixed Nautobot namespace, or the name of the subnet's VRF (``namespace_from_vrf``).
"""

from __future__ import annotations

import ipaddress
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from models.aci_subnets import AciSubnet
from services.nautobot.prefix_reader import NautobotPrefix

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _network(value: str) -> _Network:
    return ipaddress.ip_network(value, strict=False)


def parse_scope_prefixes(scope_prefixes: Sequence[str]) -> list[_Network]:
    """The scope prefixes as networks (host bits allowed); ``ValueError`` for anything else."""
    networks = []
    for raw in scope_prefixes:
        try:
            networks.append(_network(raw))
        except ValueError as exc:
            raise ValueError(f"scope_prefixes: '{raw}' is not a prefix") from exc
    return networks


def _owner(subnet: AciSubnet) -> dict[str, Any]:
    return {
        "tenant": subnet.tenant,
        "vrf": subnet.vrf,
        "bridge_domain": subnet.bridge_domain,
        "owner": subnet.owner,
        "epg": subnet.epg,
    }


def _item(subnet: AciSubnet, namespace: str | None) -> dict[str, Any]:
    return {
        "prefix": subnet.prefix,
        "gateway": subnet.gateway,
        "namespace": namespace,
        **_owner(subnet),
        "scope": list(subnet.scope),
    }


class _CoverIndex:
    """Nautobot prefixes by namespace, IP version and prefix length, for "the smallest prefix
    that contains this one".

    A lookup walks the possible prefix lengths from the longest down (at most 128 set lookups),
    so it does not depend on how many Nautobot prefixes there are. The first version scanned the
    whole prefix list once per missing ACI subnet (hundreds of millions of checks on a large
    fabric). A prefix that does not parse is left out, as it could never contain anything.
    """

    def __init__(self, nautobot: Sequence[NautobotPrefix]) -> None:
        self._by_length: dict[tuple[str | None, int], dict[int, set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for candidate in nautobot:
            try:
                network = _network(candidate.prefix)
            except ValueError:  # noqa: S112 - a prefix that does not parse can contain nothing
                continue
            key = (candidate.namespace, network.version)
            self._by_length[key][network.prefixlen].add(int(network.network_address))

    def covering(self, prefix: str, namespace: str | None) -> str | None:
        """The smallest larger prefix of ``namespace`` that contains ``prefix``, as text.

        Only meaningful for a prefix Nautobot does not have, so a containing prefix is larger.
        """
        target = _network(prefix)
        lengths = self._by_length.get((namespace, target.version))
        if not lengths:
            return None
        bits = target.max_prefixlen
        address = int(target.network_address)
        for length in range(target.prefixlen - 1, -1, -1):
            if length not in lengths:
                continue
            masked = (address >> (bits - length)) << (bits - length)
            if masked in lengths[length]:
                return str(ipaddress.ip_network((masked, length)))
        return None


def compare_subnets(
    aci: Sequence[AciSubnet],
    nautobot: Sequence[NautobotPrefix],
    *,
    namespace: str,
    namespace_from_vrf: bool,
    scope_prefixes: Sequence[str],
) -> dict[str, Any]:
    """The report: matched, missing in Nautobot, missing in ACI (when scoped), overlaps, skipped."""
    scopes = parse_scope_prefixes(scope_prefixes)
    present = {(p.namespace, p.prefix) for p in nautobot}
    cover = _CoverIndex(nautobot)

    matched: dict[tuple[str | None, str], dict[str, Any]] = {}
    missing: dict[tuple[str | None, str], dict[str, Any]] = {}
    owners: dict[tuple[str | None, str], dict[tuple[Any, ...], AciSubnet]] = defaultdict(dict)
    skipped: list[dict[str, Any]] = []

    for subnet in sorted(
        aci, key=lambda s: (s.tenant, s.prefix, s.bridge_domain or "", s.epg or "")
    ):
        target_ns = subnet.vrf if namespace_from_vrf else namespace
        if target_ns is None:
            skipped.append({"prefix": subnet.prefix, "reason": "no_vrf", **_owner(subnet)})
            continue
        key = (target_ns, subnet.prefix)
        owners[key][(subnet.tenant, subnet.bridge_domain, subnet.owner, subnet.epg)] = subnet
        if key in matched or key in missing:
            continue
        if key in present:
            matched[key] = _item(subnet, target_ns)
        else:
            missing[key] = {
                **_item(subnet, target_ns),
                "covered_by": cover.covering(subnet.prefix, target_ns),
            }

    overlaps = [
        {
            "prefix": key[1],
            "namespace": key[0],
            "owners": [_owner(s) for s in group.values()],
        }
        for key, group in owners.items()
        if len(group) > 1
    ]

    missing_in_aci = _missing_in_aci(nautobot, set(owners), scopes, namespace, namespace_from_vrf)
    summary = {
        "aci_subnets": len(aci),
        "matched": len(matched),
        "missing_in_nautobot": len(missing),
        "missing_in_aci": None if missing_in_aci is None else len(missing_in_aci),
        "overlaps": len(overlaps),
        "skipped": len(skipped),
        "differences": bool(missing or overlaps or missing_in_aci),
    }
    return {
        "namespace_mode": "vrf" if namespace_from_vrf else "fixed",
        "namespace": None if namespace_from_vrf else namespace,
        "scope_prefixes": [str(n) for n in scopes],
        "summary": summary,
        "matched": list(matched.values()),
        "missing_in_nautobot": list(missing.values()),
        "missing_in_aci": missing_in_aci,
        "overlaps": overlaps,
        "skipped": skipped,
    }


def _missing_in_aci(
    nautobot: Sequence[NautobotPrefix],
    aci_keys: set[tuple[str | None, str]],
    scopes: list[_Network],
    namespace: str,
    namespace_from_vrf: bool,
) -> list[dict[str, Any]] | None:
    """Nautobot networks inside a scope prefix that no ACI subnet accounts for (None = no scope)."""
    if not scopes:
        return None
    found = []
    for candidate in sorted(nautobot, key=lambda p: (p.namespace or "", p.prefix)):
        if candidate.type not in (None, "network"):
            continue  # containers and pools are not subnets ACI would hold
        if not namespace_from_vrf and candidate.namespace != namespace:
            continue
        network = _network(candidate.prefix)
        inside = any(
            network.version == scope.version and network != scope and network.subnet_of(scope)  # type: ignore[arg-type]
            for scope in scopes
        )
        if inside and (candidate.namespace, candidate.prefix) not in aci_keys:
            found.append(
                {
                    "prefix": candidate.prefix,
                    "namespace": candidate.namespace,
                    "status": candidate.status,
                }
            )
    return found
