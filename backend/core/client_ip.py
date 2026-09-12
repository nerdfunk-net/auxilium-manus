"""Resolve the real client IP for a request.

The backend is only reached through a proxy (the Next.js ``/api/proxy`` route,
optionally behind an ingress). ``X-Forwarded-For`` is honoured only when the
direct peer lies inside ``TRUSTED_PROXY_IPS`` (IPs or CIDRs), and the chosen
entry is the **rightmost address that is not itself a trusted proxy** — i.e. the
last hop a trusted proxy appended. The leftmost entry is client-controlled and is
never used. ``X-Real-IP`` is deliberately ignored (Next.js never sets it).

This is the single implementation for login and webhook rate-limit keys
(``routers/auth.py`` and ``services/change_requests/webhook_service.py``).
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import Request

from core.config import settings

UNKNOWN_CLIENT_HOST = "unknown"


def is_trusted_proxy(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in settings.trusted_proxy_networks)


def _forwarded_chain(request: Request) -> list[str]:
    raw = request.headers.get("x-forwarded-for") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def resolve_client_host(request: Request) -> str:
    direct = request.client.host if request.client else UNKNOWN_CLIENT_HOST
    if not is_trusted_proxy(direct):
        return direct

    for candidate in reversed(_forwarded_chain(request)):
        try:
            ip_address(candidate)
        except ValueError:
            # A malformed chain is not trusted at all; fall back to the proxy.
            return direct
        if not is_trusted_proxy(candidate):
            return candidate
    return direct
