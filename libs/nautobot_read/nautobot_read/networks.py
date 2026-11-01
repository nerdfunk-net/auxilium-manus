"""Validation of IP addresses and prefixes before they reach Nautobot.

Nautobot is lenient in unhelpful ways: a malformed ``contains`` value is silently ignored
(and returns every prefix), and a malformed ``address`` surfaces as a raw GraphQL error. So
every network value is checked here and rejected with a message the model can act on.
"""

from __future__ import annotations

import ipaddress


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
