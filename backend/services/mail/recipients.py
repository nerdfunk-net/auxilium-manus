"""Which recipients the mail settings allow."""

from __future__ import annotations

from collections.abc import Sequence


def disallowed_recipients(recipients: Sequence[str], allowed_domains: Sequence[str]) -> list[str]:
    """The addresses whose domain is neither an allowed domain nor a subdomain of one.
    An empty allow-list allows every domain."""
    if not allowed_domains:
        return []
    allowed = tuple(d.lower() for d in allowed_domains)
    blocked = []
    for address in recipients:
        domain = address.rsplit("@", 1)[-1].lower()
        if not any(domain == d or domain.endswith(f".{d}") for d in allowed):
            blocked.append(address)
    return blocked
