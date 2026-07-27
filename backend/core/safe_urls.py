"""Outbound URL policy for admin-configured HTTP integrations (ISE, Nautobot)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from core.config import settings

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal"})


class UnsafeURLError(ValueError):
    """Raised when a source URL violates the outbound HTTP policy."""


def validate_outbound_http_url(url: str, *, resolve_dns: bool = True) -> str:
    """Return a normalized URL or raise ``UnsafeURLError``.

    Allows RFC1918 / normal corporate hosts. Blocks non-http(s) schemes,
    URL userinfo, link-local / metadata targets, and (by default) loopback.
    When ``resolve_dns`` is True, every resolved A/AAAA address is checked
    (mitigates simple DNS rebinding between configure and request).
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURLError("URL is required")

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL must not contain embedded credentials")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeURLError("URL host is required")
    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"URL host is not allowed: {host}")

    # Literal IP in the URL
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        _assert_ip_allowed(literal_ip)

    if resolve_dns:
        _assert_resolved_hosts_allowed(host)

    return raw.rstrip("/")


def _assert_resolved_hosts_allowed(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"URL host could not be resolved: {host}") from exc
    if not infos:
        raise UnsafeURLError(f"URL host could not be resolved: {host}")
    for info in infos:
        sockaddr = info[4]
        _assert_ip_allowed(ipaddress.ip_address(sockaddr[0]))


def _assert_ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if ip.is_unspecified or ip.is_multicast:
        raise UnsafeURLError(f"URL resolves to a disallowed address: {ip}")
    if ip.is_loopback:
        if not getattr(settings, "allow_loopback_source_urls", False):
            raise UnsafeURLError(f"URL resolves to loopback address: {ip}")
        return
    if ip.is_link_local:
        raise UnsafeURLError(f"URL resolves to link-local address: {ip}")
    # Intentionally allow is_private (RFC1918) for on-prem ISE/Nautobot.
