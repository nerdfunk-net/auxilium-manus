"""Parse and expand IPv4 ranges for the ping handler (pure functions, no I/O).

Accepted, separated by commas, semicolons or new lines::

    10.0.0.5                single address
    10.0.0.0/24             network (network and broadcast address left out up to /30)
    10.0.0.5-10.0.0.40      inclusive range
    10.0.0.5-40             short range: only the last octet of the end is given

Everything is checked before a single address is generated, so a request for ``10.0.0.0/8`` is
refused by arithmetic and never allocates a list. Error messages never echo the input.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable

MAX_INPUT_CHARS = 4096
_SPLIT = re.compile(r"[,;\n]")
_DIGITS = re.compile(r"^\d{1,3}$")

IPv4Network = ipaddress.IPv4Network


# Never a ping target, whatever the allow-list says: "this network", loopback, link-local (cloud
# metadata is 169.254.169.254), multicast and the reserved block (incl. 255.255.255.255). A
# directed broadcast (x.x.x.255 of a /24) cannot be recognised without knowing the subnet; a CIDR
# range already leaves its own broadcast address out.
_NEVER = tuple(
    (int(net.network_address), int(net.broadcast_address))
    for net in map(
        ipaddress.IPv4Network,
        ("0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "240.0.0.0/4"),
    )
)


class RangeError(ValueError):
    """The range text is not usable; the message is safe to show to the user."""


def parse_networks(text: str | None) -> tuple[IPv4Network, ...]:
    """Parse the operator's allow-list (``10.0.0.0/8, 192.168.0.0/16``). Empty means no limit."""
    if text is None or not text.strip():
        return ()
    return tuple(
        ipaddress.IPv4Network(part.strip(), strict=False)
        for part in _SPLIT.split(text)
        if part.strip()
    )


def _address(text: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(text.strip())
    except ValueError as exc:
        raise RangeError("only IPv4 addresses are supported (a.b.c.d)") from exc


def _token_bounds(token: str) -> tuple[int, int]:
    """First and last address (as integers) a single token stands for."""
    if "/" in token:
        try:
            network = ipaddress.IPv4Network(token.strip(), strict=False)
        except ValueError as exc:
            raise RangeError("only IPv4 networks are supported (a.b.c.d/len)") from exc
        first, last = int(network.network_address), int(network.broadcast_address)
        if network.prefixlen <= 30:
            first, last = first + 1, last - 1
        return first, last
    if "-" in token:
        left, _, right = token.partition("-")
        start = _address(left)
        right = right.strip()
        if _DIGITS.fullmatch(right):
            octet = int(right)
            if octet > 255:
                raise RangeError("the end of a short range must be 0-255")
            end = ipaddress.IPv4Address((int(start) & 0xFFFFFF00) | octet)
        else:
            end = _address(right)
        if int(end) < int(start):
            raise RangeError("a range must not end before it starts")
        return int(start), int(end)
    address = int(_address(token))
    return address, address


def _within(first: int, last: int, allowed: Iterable[IPv4Network]) -> bool:
    merged = list(ipaddress.collapse_addresses(allowed))
    span = ipaddress.summarize_address_range(
        ipaddress.IPv4Address(first), ipaddress.IPv4Address(last)
    )
    return all(any(piece.subnet_of(net) for net in merged) for piece in span)


def expand_ranges(
    text: object,
    *,
    max_hosts: int,
    allowed: tuple[IPv4Network, ...] = (),
) -> list[str]:
    """Every address *text* stands for, unique and in ascending order."""
    if not isinstance(text, str) or not text.strip():
        raise RangeError("the range is missing: give an address, a network or a range")
    if len(text) > MAX_INPUT_CHARS:
        raise RangeError(f"the range text is longer than {MAX_INPUT_CHARS} characters")

    bounds = [_token_bounds(token.strip()) for token in _SPLIT.split(text) if token.strip()]
    if not bounds:
        raise RangeError("the range is missing: give an address, a network or a range")

    for first, last in bounds:
        if any(first <= high and last >= low for low, high in _NEVER):
            raise RangeError(
                "the range includes addresses that are not pingable here "
                "(0.0.0.0/8, loopback, link-local, multicast, reserved)"
            )

    if allowed:
        for first, last in bounds:
            if first <= last and not _within(first, last, allowed):
                raise RangeError("the range is outside the networks this agent is allowed to ping")

    if sum(max(0, last - first + 1) for first, last in bounds) > max_hosts:
        raise RangeError(f"the range has more than {max_hosts} addresses (the limit of this agent)")

    unique: set[int] = set()
    for first, last in bounds:
        unique.update(range(first, last + 1))
    return [str(ipaddress.IPv4Address(value)) for value in sorted(unique)]
