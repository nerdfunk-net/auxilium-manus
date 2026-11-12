"""Where the discover-network step may log in: permitted prefixes and the host policy.

Pure functions. A host found through CDP is attacker-influenced data, so it is only visited
when it lies inside a prefix the workflow author listed, passes the app-wide host policy and
the operator has switched following on (``DISCOVER_NETWORK_FOLLOW_ENABLED``).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from core.safe_hosts import validate_device_host

STEP_ID = "discover-network"
MAX_PREFIXES = 50
# A permitted prefix must be at least this specific: a /7 or /0 is "the whole internet".
MIN_PREFIX_LENGTH = 8

_BLOCKED = tuple(
    ipaddress.ip_network(net)
    for net in ("0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "240.0.0.0/4")
)

Prefixes = tuple[ipaddress.IPv4Network, ...]


def _split(raw: object) -> list[object]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part for chunk in raw.splitlines() for part in chunk.split(",")]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raise ValueError(f"{STEP_ID}: permitted_prefixes must be a list of CIDR prefixes")


def _parse_one(entry: object) -> ipaddress.IPv4Network:
    if not isinstance(entry, str):
        raise ValueError(f"{STEP_ID}: every permitted prefix must be text in CIDR form")
    text = entry.strip()
    if "/" not in text:
        raise ValueError(
            f"{STEP_ID}: {text!r} is not a prefix in CIDR form (for example 10.1.0.0/16)"
        )
    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise ValueError(f"{STEP_ID}: {text!r} is not a valid CIDR prefix") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError(f"{STEP_ID}: {text!r}: only IPv4 prefixes are supported")
    if network.prefixlen < MIN_PREFIX_LENGTH:
        raise ValueError(
            f"{STEP_ID}: {text!r} is too broad; use /{MIN_PREFIX_LENGTH} or more specific"
        )
    if any(network.overlaps(blocked) for blocked in _BLOCKED):
        raise ValueError(f"{STEP_ID}: {text!r} contains addresses that are never allowed")
    return network


def parse_prefixes(raw: object) -> Prefixes:
    """The permitted prefixes as networks, in input order, without duplicates.

    Accepts a list or text separated by newlines or commas. Raises ``ValueError`` for anything
    malformed, IPv6, too broad (shorter than /8) or overlapping loopback, link-local, multicast
    and reserved space.
    """
    networks: list[ipaddress.IPv4Network] = []
    for entry in _split(raw):
        if isinstance(entry, str) and not entry.strip():
            continue
        network = _parse_one(entry)
        if network not in networks:
            networks.append(network)
    if len(networks) > MAX_PREFIXES:
        raise ValueError(f"{STEP_ID}: at most {MAX_PREFIXES} permitted prefixes are allowed")
    return tuple(networks)


def in_scope(ip: str, prefixes: Iterable[ipaddress.IPv4Network]) -> bool:
    """True when *ip* is an IPv4 address inside one of the prefixes."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    return any(address in network for network in prefixes)


def check_discovered_host(host: str) -> None:
    """Raise ``ValueError`` for a host the app must never log into.

    The app-wide host policy (``validate_device_host``): no loopback, link-local (the cloud
    metadata address), unspecified or multicast literal and no metadata host name. That a host
    lies in a permitted prefix is checked separately (``in_scope``).
    """
    validate_device_host(host)


def ensure_following_allowed(*, enabled: bool) -> None:
    """Raise ``ValueError`` when the operator has not allowed following neighbours.

    ``enabled`` is ``settings.discover_network_follow_enabled``
    (``DISCOVER_NETWORK_FOLLOW_ENABLED``). Not the template-preview switch
    ``ALLOW_NETMIKO_ARBITRARY_HOSTS``: startup refuses that one outside development.
    Checked once at the start of a run, so the author gets the reason before any login.
    """
    if not enabled:
        raise ValueError(
            f"{STEP_ID}: following neighbours is switched off; the operator must set "
            "DISCOVER_NETWORK_FOLLOW_ENABLED=true"
        )
