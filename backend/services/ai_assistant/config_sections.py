"""Cut sections out of a device configuration text (pure functions, no I/O).

A section is a top-level line (column 0) plus the lines under it that are indented, e.g.
``router ospf 100`` and its children. This holds for IOS, IOS-XE, NX-OS and IOS-XR; ``!`` lines
are separators and end a section. Banners (``banner motd ^C ... ^C``) are one section that runs to
the closing delimiter. The original text of each section is kept unchanged.

The input is the already redacted text; nothing here reads a secret.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# A topic is a list of top-level line prefixes (lower case, matched at a word boundary). The
# model picks the topic name; it never writes a pattern for it.
TOPICS: dict[str, tuple[str, ...]] = {
    "ospf": ("router ospf", "router ospfv3", "ipv6 router ospf"),
    "bgp": ("router bgp",),
    "eigrp": ("router eigrp",),
    "isis": ("router isis",),
    "rip": ("router rip", "ipv6 router rip"),
    "static_routes": ("ip route", "ipv6 route", "ip default-gateway"),
    "route_policy": (
        "route-map",
        "ip prefix-list",
        "ipv6 prefix-list",
        "ip community-list",
        "ip as-path access-list",
        "route-policy",
        "prefix-set",
        "community-set",
        "as-path-set",
    ),
    "vrf": ("vrf definition", "ip vrf", "vrf context"),
    "interfaces": ("interface",),
    "access_lists": (
        "access-list",
        "ip access-list",
        "ipv6 access-list",
        "mac access-list",
        "ip access-class",
        "object-group",
    ),
    "vty_lines": ("line vty", "line con", "line console", "line aux"),
    "authentication": (
        "aaa",
        "username",
        "enable",
        "tacacs",
        "tacacs-server",
        "radius",
        "radius-server",
        "ldap",
        "key chain",
        "ip ssh",
        "login block-for",
        "login on-failure",
        "login on-success",
        "security passwords",
        "service password-encryption",
    ),
}
_ROUTING_PARTS = ("ospf", "bgp", "eigrp", "isis", "rip", "static_routes", "route_policy", "vrf")
TOPICS["routing"] = (
    *dict.fromkeys(prefix for name in _ROUTING_PARTS for prefix in TOPICS[name]),
    "ip routing",
    "ipv6 unicast-routing",
    "ip cef",
    "ip multicast-routing",
    "router ",
)
TopicName = Literal[
    "routing",
    "ospf",
    "bgp",
    "eigrp",
    "isis",
    "rip",
    "static_routes",
    "route_policy",
    "vrf",
    "interfaces",
    "access_lists",
    "vty_lines",
    "authentication",
]

_BANNER = re.compile(r"^banner\s+\S+\s+(\S)", re.IGNORECASE)
MAX_PATTERN_CHARS = 200


@dataclass(frozen=True)
class Section:
    header: str
    start_line: int  # 1-based
    end_line: int  # 1-based, inclusive
    text: str

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def _is_separator(line: str) -> bool:
    return not line.strip() or line.strip() == "!"


def _banner_end(lines: list[str], index: int) -> int:
    """Index of the last line of the banner that starts at ``index`` (itself if it is closed)."""
    match = _BANNER.match(lines[index])
    if match is None:
        return index
    delimiter = match.group(1)
    if lines[index].count(delimiter) >= 2 and lines[index].rstrip().endswith(delimiter):
        return index
    for later in range(index + 1, len(lines)):
        if delimiter in lines[later]:
            return later
    return len(lines) - 1


def split_sections(text: str) -> list[Section]:
    """Every top-level block of ``text`` in file order. Separator lines belong to no section."""
    lines = text.splitlines()
    sections: list[Section] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_separator(line) or line[0] in " \t":
            index += 1  # a stray indented line (no header above it) is not a section
            continue
        end = _banner_end(lines, index)
        if end == index:
            while end + 1 < len(lines) and lines[end + 1][:1] in (" ", "\t"):
                end += 1
        sections.append(
            Section(line.rstrip(), index + 1, end + 1, "\n".join(lines[index : end + 1]))
        )
        index = end + 1
    return sections


def _matches_prefix(header: str, prefix: str, case_sensitive: bool) -> bool:
    head = header if case_sensitive else header.lower()
    want = prefix if case_sensitive else prefix.lower()
    if not head.startswith(want):
        return False
    # "router ospf" matches "router ospf 100" but "ip route" must not match "ip routing".
    rest = head[len(want) :]
    return not rest or rest[0].isspace() or want.endswith(" ")


def select_by_prefix(
    sections: list[Section], prefix: str, *, case_sensitive: bool = False
) -> list[Section]:
    """Sections whose first line starts with ``prefix``.

    Whole words first: ``router ospf 100`` does not also pick up ``router ospf 1000``. When
    nothing matches that way, a plain prefix match is used, so ``interface Loopback`` finds
    ``interface Loopback0``.
    """
    wanted = " ".join(prefix.split())
    strict = [
        s for s in sections if _matches_prefix(" ".join(s.header.split()), wanted, case_sensitive)
    ]
    if strict:
        return strict
    fold = (lambda text: text) if case_sensitive else str.lower
    return [s for s in sections if fold(" ".join(s.header.split())).startswith(fold(wanted))]


def select_by_topic(sections: list[Section], topic: str) -> list[Section]:
    prefixes = TOPICS[topic]
    return [
        s
        for s in sections
        if any(_matches_prefix(" ".join(s.header.split()), p, False) for p in prefixes)
    ]


def select_by_regex(
    sections: list[Section], pattern: str, *, case_sensitive: bool = False
) -> list[Section]:
    """Sections whose header line matches ``pattern`` (``re.search``).

    Raises ``ValueError`` for an invalid or over-long pattern. The pattern runs on header lines
    only (short), and is capped, but it is model-written: the caller runs it off the event loop.
    """
    if len(pattern) > MAX_PATTERN_CHARS:
        raise ValueError(f"pattern is longer than {MAX_PATTERN_CHARS} characters")
    try:
        compiled = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc
    return [s for s in sections if compiled.search(s.header[:500])]


def outline(sections: list[Section]) -> list[dict[str, object]]:
    """Headers with their line range, for 'what sections does this config have'."""
    return [
        {
            "header": s.header[:200],
            "lines": f"{s.start_line}-{s.end_line}",
            "line_count": s.line_count,
        }
        for s in sections
    ]
