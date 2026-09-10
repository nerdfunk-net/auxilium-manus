"""Resolve the real client IP for a request, honouring X-Forwarded-For only
when the direct peer is a configured trusted proxy (``TRUSTED_PROXY_IPS``).

Mirrors the logic in ``routers/auth.py`` so webhook rate-limiting keys are
computed the same way as login rate-limiting keys.
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import Request

from core.config import settings


def resolve_client_host(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    if direct not in settings.trusted_proxy_ips:
        return direct

    forwarded_for = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    candidate = (
        forwarded_for.split(",", maxsplit=1)[0].strip() if forwarded_for else real_ip
    )
    if candidate is None:
        return direct
    try:
        ip_address(candidate)
    except ValueError:
        return direct
    return candidate
