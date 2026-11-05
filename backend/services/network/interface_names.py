"""Canonical interface names, so CDP, LLDP, Batfish, configs and Nautobot can be compared.

The same port appears as ``Gig 1/0/1`` (CDP summary), ``GigabitEthernet1/0/1`` (CDP detail,
configs, Batfish), ``Gi1/0/1`` (route tables) and ``Eth1/1`` / ``Ethernet1/1`` (NX-OS). The
canonical form is the long IOS-style name without a space. Names that match no known prefix
(``mgmt0``, ``ge-0/0/1``, ``Management``) are returned trimmed and unchanged, so a comparison of
two unknown names is still exact. Pure and side-effect free (doc/AI_TOOL_CHAIN.md §24.14).
"""

from __future__ import annotations

import re

# (alias prefixes in lower case, canonical long name). Longest alias wins, so ``twe`` is never read
# as ``t`` + ``we``. An alias must be followed by a digit (optionally after spaces) to count.
_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("gigabitethernet", "gigabit", "gig", "gi"), "GigabitEthernet"),
    (("fastethernet", "fas", "fa"), "FastEthernet"),
    (("tengigabitethernet", "tengigabit", "tengige", "ten", "te"), "TenGigabitEthernet"),
    (("twentyfivegige", "twe"), "TwentyFiveGigE"),
    (("fortygigabitethernet", "fortygige", "fo"), "FortyGigabitEthernet"),
    (("hundredgige", "hu"), "HundredGigE"),
    (("ethernet", "eth"), "Ethernet"),
    (("port-channel", "portchannel", "po"), "Port-channel"),
    (("loopback", "lo"), "Loopback"),
    (("vlan", "vl"), "Vlan"),
)

_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((alias, canonical) for aliases, canonical in _PREFIXES for alias in aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)
_NAME = re.compile(r"(?P<prefix>[A-Za-z-]+?)\s*(?P<rest>\d[\d/.:]*)", re.ASCII)


def canonical_interface_name(raw: str) -> str:
    """The canonical long name of ``raw``, or ``raw`` trimmed when its prefix is unknown."""
    name = raw.strip()
    match = _NAME.fullmatch(name)
    if match is None:
        return name
    prefix = match.group("prefix").lower()
    for alias, canonical in _ALIASES:
        if prefix == alias:
            return f"{canonical}{match.group('rest')}"
    return name


def same_interface(first: str, second: str) -> bool:
    """True when both names are non-empty and canonicalise to the same port."""
    left = canonical_interface_name(first).lower()
    right = canonical_interface_name(second).lower()
    return bool(left) and left == right
