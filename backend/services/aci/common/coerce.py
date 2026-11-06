"""Lenient scalar coercion for APIC payloads.

APIC sends every attribute as a string and uses ``""`` (or ``0.0.0.0``) for "unset", so
normalization maps anything unusable to ``None`` instead of failing.
"""

from __future__ import annotations

import ipaddress
from typing import Any


def text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    result = str(value).strip()
    return result or None


def integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def usable_ipv4(value: Any) -> str | None:
    """A real unicast-style IPv4 address, or ``None`` (``0.0.0.0`` means "not set")."""
    candidate = text(value)
    if candidate is None:
        return None
    try:
        address = ipaddress.IPv4Address(candidate)
    except ValueError:
        return None
    if address.is_unspecified:
        return None
    return str(address)
