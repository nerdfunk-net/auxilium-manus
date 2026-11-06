"""Validation of IP addresses and prefixes before they reach Nautobot.

Nautobot is lenient in unhelpful ways: a malformed ``contains`` value is silently ignored
(and returns every prefix), and a malformed ``address`` surfaces as a raw GraphQL error. So
every network value is checked here and rejected with a message the model can act on.
"""

from __future__ import annotations

import ipaddress
import re


class InvalidInputError(ValueError):
    """A tool argument is malformed; the message is written for the calling LLM."""


def address(value: str) -> str:
    """An IPv4/IPv6 address, with or without ``/mask`` (returned as given, stripped)."""
    text = value.strip()
    try:
        ipaddress.ip_interface(text)
    except ValueError as exc:
        raise InvalidInputError(
            f"'{value}' is not a valid IP address (examples: 10.0.0.2, 10.0.0.2/24, 2001:db8::1)."
        ) from exc
    return text


def prefix(value: str) -> str:
    """A network in CIDR notation; host bits are cleared (10.0.0.7/24 becomes 10.0.0.0/24)."""
    try:
        return str(ipaddress.ip_network(value.strip(), strict=False))
    except ValueError as exc:
        raise InvalidInputError(
            f"'{value}' is not a valid IP prefix (examples: 10.0.0.0/24, 2001:db8::/32)."
        ) from exc


_MAC_SEPARATORS = re.compile(r"[.:\-\s]")
_MAC_DIGITS = re.compile(r"[0-9a-f]{12}")


def mac_address(value: str) -> str:
    """A MAC address in any common notation, as ``AA:BB:CC:DD:EE:FF``.

    Accepts colon, dash, Cisco-dotted (``aabb.cc00.0100``) and bare 12-digit forms in any case.
    Nautobot normalizes a MAC itself, but a malformed one surfaces as a raw GraphQL error, so it
    is checked here and rejected with a message the model can act on.
    """
    digits = _MAC_SEPARATORS.sub("", value).lower()
    if not _MAC_DIGITS.fullmatch(digits):
        raise InvalidInputError(
            f"'{value}' is not a valid MAC address "
            "(examples: aa:bb:cc:00:01:00, aabb.cc00.0100, aa-bb-cc-00-01-00)."
        )
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()
