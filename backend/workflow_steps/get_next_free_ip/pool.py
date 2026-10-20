"""Pure helpers: pick free addresses at or after a start offset and hand them out."""

from __future__ import annotations

import ipaddress
from typing import Any


def bare_address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address when *text* is a single IP without a prefix length, else None."""
    value = text.strip()
    if "/" in value:
        return None
    return _as_address(value)


def parse_prefix(text: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Parse ``address/length`` and return the network it belongs to.

    A host address with a length (``192.168.178.240/24``, e.g. ``{device.primary_ip4_cidr}``)
    gives its network (``192.168.178.0/24``). A bare address has no length to compute from;
    the caller finds its prefix in Nautobot (see ``bare_address``).
    """
    value = text.strip()
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(
            f"{value!r} is not a valid prefix; use CIDR form such as 192.168.178.0/24 "
            "or a device address"
        ) from exc


def _as_address(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def free_addresses_from(
    available: list[Any],
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
    start_offset: int,
) -> list[str]:
    """Bare free addresses inside *network* at or after ``network_address + start_offset``.

    *available* is the body of ``/ipam/prefixes/{id}/available-ips/``. Entries that are not
    ``{"address": "<ip>/<len>"}`` or lie outside the prefix are ignored.
    """
    first = int(network.network_address) + start_offset
    found: list[str] = []
    for item in available:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("address") or "").split("/", 1)[0].strip()
        address = _as_address(raw)
        if address is None:
            continue
        if address.version != network.version or address not in network:
            continue
        if int(address) >= first:
            found.append(str(address))
    return found


def window_size(start_offset: int, count: int, devices: int, *, cap: int) -> int:
    """How many available addresses to ask Nautobot for.

    Nautobot lists free addresses from the start of the prefix, and at most ``start_offset``
    of them lie before the start point, so ``start_offset + count * devices`` always reaches
    enough addresses past it.
    """
    return min(cap, start_offset + count * devices)


def take(pool: list[str], used: int, count: int) -> list[str] | None:
    """``count`` addresses starting at index *used*, or None when the pool is too short."""
    chunk = pool[used : used + count]
    return chunk if len(chunk) == count else None
