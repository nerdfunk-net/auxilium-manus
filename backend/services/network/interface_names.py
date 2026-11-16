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
    (("ethernet", "eth", "et"), "Ethernet"),
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


# The short forms people and tables (MAC table, client data) use for a canonical long name. IOS
# prints ``Et1/5`` and NX-OS ``Eth1/5`` for ``Ethernet1/5``.
_SHORT_NAMES: dict[str, tuple[str, ...]] = {
    "GigabitEthernet": ("Gi",),
    "FastEthernet": ("Fa",),
    "TenGigabitEthernet": ("Te",),
    "TwentyFiveGigE": ("Twe",),
    "FortyGigabitEthernet": ("Fo",),
    "HundredGigE": ("Hu",),
    "Ethernet": ("Eth", "Et"),
    "Port-channel": ("Po",),
    "Loopback": ("Lo",),
    "Vlan": ("Vl",),
}


def is_complete_interface_name(raw: str) -> bool:
    """True for a whole interface name of a known kind (``Po51``, ``Gi1/0/1``), not for a part.

    ``Gi1/0/``, ``Gi`` and ``mgmt0`` are not: a tool treats them as text to look for.
    """
    match = _NAME.fullmatch(raw.strip())
    if match is None or not match.group("rest")[-1].isdigit():
        return False
    prefix = match.group("prefix").lower()
    return any(prefix == alias for alias, _ in _ALIASES)


def interface_name_variants(raw: str) -> tuple[str, ...]:
    """The spellings to try for ``raw``: as typed, the canonical long name and the short forms.

    ``Po51`` -> ``Po51``, ``Port-channel51``; ``port-channel 51`` -> ``port-channel 51``,
    ``Port-channel51``, ``Po51``. A name that is not one interface name (an unknown prefix, or
    trailing text) has only the form as typed.
    """
    typed = raw.strip()
    if _NAME.fullmatch(typed) is None:
        return (typed,) if typed else ()
    canonical = canonical_interface_name(typed)
    variants = [typed, canonical]
    for long_name, shorts in _SHORT_NAMES.items():
        if canonical.startswith(long_name) and canonical[len(long_name) :][:1].isdigit():
            variants.extend(f"{short}{canonical[len(long_name) :]}" for short in shorts)
    seen: set[str] = set()
    unique: list[str] = []
    for name in variants:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique.append(name)
    return tuple(unique)
