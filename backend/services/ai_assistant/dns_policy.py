"""What Ask the Net may send to the DNS resolver (doc/AI_TOOL_CHAIN.md §50).

A DNS query leaves the building: the name reaches whatever server is authoritative for it. A
prompt-injected model could therefore smuggle data out in a name such as
``<secret>.attacker.example``. The control is not the model's good behaviour but this module:
a forward lookup is allowed only for a name under a suffix the operator listed in
``AI_DNS_ALLOWED_SUFFIXES``. A reverse lookup carries an IP address, at most 128 bits, so it
needs no list, but special-purpose addresses are refused. Pure functions, no I/O.
"""

from __future__ import annotations

import ipaddress

from core.dns_names import is_valid_dns_name, normalize_suffix, normalize_suffixes

__all__ = [
    "DnsPolicyError",
    "forward_name",
    "normalize_suffix",
    "normalize_suffixes",
    "reverse_address",
]


class DnsPolicyError(ValueError):
    """The query is not allowed. The message is written for the model and the user."""


def forward_name(name: str, suffixes: tuple[str, ...]) -> str:
    """The lower-case name to resolve, or ``DnsPolicyError``.

    Single-label names are refused because the system resolver would expand them with its search
    domains, which would step around the suffix check.
    """
    if not suffixes:
        raise DnsPolicyError(
            "Name lookups are not enabled: the operator has not listed any domain in "
            "AI_DNS_ALLOWED_SUFFIXES. Only reverse lookups of IP addresses are possible."
        )
    candidate = name.strip().rstrip(".").lower()
    if not is_valid_dns_name(candidate) or "." not in candidate:
        raise DnsPolicyError(f"{name!r} is not a fully qualified host name")
    if not any(candidate.endswith("." + suffix) for suffix in suffixes):
        raise DnsPolicyError(
            f"Names are resolved only under these domains: {', '.join(suffixes)}. "
            "Tell the user; do not try another spelling."
        )
    return candidate


def reverse_address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """The address to look up, or ``DnsPolicyError`` for a special-purpose address."""
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError as exc:
        raise DnsPolicyError(f"{text!r} is not an IP address") from exc
    mapped = getattr(address, "ipv4_mapped", None)
    for candidate in (address, mapped):
        if candidate is not None and (
            candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_unspecified
            or candidate.is_multicast
            or candidate.is_reserved
        ):
            raise DnsPolicyError(f"{address} is a special-purpose address and is not looked up")
    return address
