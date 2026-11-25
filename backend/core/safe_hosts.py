"""Host policy for every host the app dials: the template preview, and the SSH and ICMP steps."""

from __future__ import annotations

import ipaddress

_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.google.com"})


def validate_device_host(host: str) -> str:
    """Return a stripped host or raise ``ValueError``: the rules for any host the app connects to.

    No loopback, link-local (the cloud metadata address), unspecified or multicast literal and no
    metadata host name. A host that came from the inventory needs only this; a host a user typed
    also needs ``validate_netmiko_preview_host``'s arbitrary-host switch.
    """
    stripped = (host or "").strip()
    if not stripped:
        raise ValueError("host is required")

    lowered = stripped.lower()
    if lowered in _BLOCKED_HOSTNAMES:
        raise ValueError(f"host is not allowed: {stripped}")

    try:
        literal_ip = ipaddress.ip_address(stripped)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if literal_ip.is_unspecified or literal_ip.is_multicast or literal_ip.is_link_local:
            raise ValueError(f"host is not allowed: {stripped}")
        if literal_ip.is_loopback:
            raise ValueError(f"host is not allowed: {stripped}")
    return stripped


def validate_inventory_host(host: str, *, environment: str, allow_arbitrary: bool) -> str:
    """Return a stripped host from the inventory or raise ``ValueError``.

    A host the SSH and ICMP steps dial (set by Nautobot, Get from User or a CSV) must pass
    ``validate_device_host`` outside development. ``ENV=development`` and the
    ``allow_netmiko_arbitrary_hosts`` switch (itself refused at startup outside development)
    skip the address rules, so a lab on a loopback address keeps working.
    """
    if environment == "development" or allow_arbitrary:
        stripped = (host or "").strip()
        if not stripped:
            raise ValueError("host is required")
        return stripped
    return validate_device_host(host)


def validate_netmiko_preview_host(
    host: str,
    *,
    environment: str,
    allow_arbitrary: bool,
) -> str:
    """Return a stripped host or raise ``ValueError`` (a host the user typed)."""
    stripped = validate_device_host(host)
    if environment != "development" and not allow_arbitrary:
        raise ValueError("Netmiko preview to arbitrary hosts is disabled")
    return stripped
