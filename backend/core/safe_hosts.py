"""Host policy for the Netmiko template-preview API (not workflow-run executors)."""

from __future__ import annotations

import ipaddress

_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.google.com"})


def validate_netmiko_preview_host(
    host: str,
    *,
    environment: str,
    allow_arbitrary: bool,
) -> str:
    """Return a stripped host or raise ``ValueError``."""
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

    if environment != "development" and not allow_arbitrary:
        raise ValueError("Netmiko preview to arbitrary hosts is disabled")

    return stripped
