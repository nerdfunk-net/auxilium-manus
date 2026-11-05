"""Parsed rows -> neighbour records (doc/AI_TOOL_CHAIN.md §24.6). Pure functions.

TextFSM rows differ per platform (``mgmt_address`` / ``management_ip``, ``bgp_neighbor`` /
``bgp_neigh`` / ``peer_ip`` ...), so every concept is read through a list of candidate column
names. Text that came from a neighbouring device (system names, descriptions) is attacker
influenced: it is stripped of control characters and cut to a fixed length here, and only ever
returned as a data field.
"""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from services.ai_assistant.neighbors.catalogue import Step
from services.network.interface_names import canonical_interface_name

Row = Mapping[str, Any]
Record = dict[str, Any]

MAX_TEXT_CHARS = 100
MAX_EXAMPLE_PREFIXES = 3
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\ufeff]")

# Route codes of the IOS family and Arista (one or two letters, matched whole; case matters:
# ``i`` is IS-IS, ``I`` is IGRP).
_ROUTE_CODES = (
    ("EX", "eigrp"),
    ("D", "eigrp"),
    ("O", "ospf"),
    ("B", "bgp"),
    ("S", "static"),
    ("C", "connected"),
    ("L", "local"),
    ("R", "rip"),
    ("i", "isis"),
    ("I", "isis"),
    ("a", "isis"),
)
_ROUTE_CODE_NAMES = dict(_ROUTE_CODES)
# NX-OS (and IOS-XR) name the source with a word, often followed by a process id or AS number:
# ``static``, ``direct``, ``local``, ``ospf-1``, ``bgp-65001``, ``eigrp-100``, ``isis-1``.
_ROUTE_WORDS = {
    "static": "static",
    "direct": "connected",
    "connected": "connected",
    "local": "local",
    "ospf": "ospf",
    "bgp": "bgp",
    "eigrp": "eigrp",
    "isis": "isis",
    "rip": "rip",
}
_MIN_WORD_CHARS = 3
_FIRST_WORD = re.compile(r"[A-Za-z]+")
_DEFAULT_PREFIXES = frozenset({"0.0.0.0/0", "0.0.0.0"})  # noqa: S104 - route prefixes, not binds
# Routes that point at no neighbour.
_NO_NEIGHBOR = frozenset({"connected", "local"})


def clean_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Text from a device as plain, single-line, length-capped data (never an instruction)."""
    if value is None:
        return ""
    text = _CONTROL.sub(" ", str(value))
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def _pick(row: Row, *names: str) -> str:
    """The first non-empty column among ``names`` (a list column contributes its first item)."""
    for name in names:
        value = row.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        text = clean_text(value)
        if text:
            return text
    return ""


def _pick_all(row: Row, *names: str) -> list[str]:
    """Every value of the first non-empty column among ``names`` (list columns keep all items)."""
    for name in names:
        value = row.get(name)
        items = value if isinstance(value, (list, tuple)) else [value]
        cleaned = [t for t in (clean_text(i) for i in items) if t]
        if cleaned:
            return cleaned
    return []


def _ip_or_empty(text: str) -> str:
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return ""


def _capabilities(text: str) -> list[str]:
    return [c for c in re.split(r"[,\s]+", text) if c][:12]


def _vrf_matches(row: Row, wanted: str) -> bool:
    """Whether a row may be used for the VRF the command asked for.

    A VRF command already limits its output to that VRF, and some templates do not echo the name,
    so an empty ``vrf`` value fits any VRF. A row that names a VRF fits only that VRF (a command
    that lists several of them); ``global`` is another word for ``default``. Names compare
    case-insensitively.
    """
    own = _pick(row, "vrf")
    if not own:
        return True
    if own.lower() == "global":
        own = "default"
    return own.lower() == wanted.lower()


def _l2_record(protocol: str, row: Row) -> Record:
    ip = _ip_or_empty(_pick(row, "mgmt_address", "management_ip", "interface_ip"))
    return {
        "layer": "l2",
        "protocol": protocol,
        "local_interface": _pick(row, "local_interface"),
        "neighbor_name": _pick(row, "neighbor_name", "neighbor"),
        "neighbor_interface": _pick(row, "neighbor_port_id", "neighbor_interface"),
        "neighbor_ip": ip or None,
        "platform": _pick(row, "platform") or None,
        "capabilities": _capabilities(_pick(row, "capabilities")),
    }


def _ospf_record(row: Row, step: Step) -> Record | None:
    if not _vrf_matches(row, step.vrf):
        return None
    return {
        "layer": "l3",
        "protocol": "ospf",
        "vrf": step.vrf,
        "neighbor_ip": _ip_or_empty(_pick(row, "ip_address", "address")) or None,
        "neighbor_id": _pick(row, "neighbor_id"),
        "interface": _pick(row, "interface"),
        "state": _pick(row, "state"),
        "uptime": _pick(row, "neighbor_uptime", "uptime", "dead_time") or None,
    }


def _bgp_record(row: Row, step: Step) -> Record | None:
    if not _vrf_matches(row, step.vrf):
        return None
    peer = _ip_or_empty(_pick(row, "bgp_neigh", "bgp_neighbor", "peer_ip"))
    if not peer:
        return None
    state_text = _pick(row, "state_pfxrcd", "state_or_prefixes_received", "received")
    state_word = _pick(row, "state")
    established = state_text.isdigit() or state_word.lower().startswith("estab")
    return {
        "layer": "l3",
        "protocol": "bgp",
        "vrf": step.vrf,
        "neighbor_ip": peer,
        "remote_as": _pick(row, "neigh_as", "neighbor_as", "peer_as"),
        "local_as": _pick(row, "local_as") or None,
        "state": "Established" if established else (state_word or state_text),
        "prefixes_received": int(state_text) if state_text.isdigit() else None,
        "uptime": _pick(row, "up_down") or None,
    }


def _simple_adjacency(protocol: str, row: Row, step: Step) -> Record | None:
    if not _vrf_matches(row, step.vrf):
        return None
    return {
        "layer": "l3",
        "protocol": protocol,
        "vrf": step.vrf,
        "neighbor_ip": _ip_or_empty(_pick(row, "ip_address")) or None,
        "neighbor_id": _pick(row, "system_id", "neighbor_id"),
        "interface": _pick(row, "interface"),
        "state": _pick(row, "state"),
        "uptime": _pick(row, "uptime", "hold", "hold_time") or None,
    }


def route_protocol(code: str) -> str:
    """The routing protocol a route code stands for (``O IA`` -> ``ospf``, ``ospf-1`` -> ``ospf``).

    A word of three letters or more is a NX-OS style name and is read case-insensitively; a
    shorter token is an IOS style code and is read as written. Anything else is ``other``.
    """
    first = _FIRST_WORD.match(code.strip())
    if first is None:
        return "other"
    word = first.group(0)
    if len(word) >= _MIN_WORD_CHARS:
        return _ROUTE_WORDS.get(word.lower(), "other")
    return _ROUTE_CODE_NAMES.get(word, "other")


def _route_rows(rows: Iterable[Row], step: Step) -> list[Record]:
    """One record per route and next hop; connected and local routes are kept for the counts."""
    routes: list[Record] = []
    for row in rows:
        if not _vrf_matches(row, step.vrf):
            continue
        protocol = route_protocol(_pick(row, "protocol"))
        prefix_length = _pick(row, "prefix_length")
        network = _pick(row, "network")
        hops = _pick_all(row, "nexthop_ip", "next_hop")
        interfaces = _pick_all(row, "nexthop_if", "interface")
        base = {
            "protocol": protocol,
            "prefix": f"{network}/{prefix_length}" if network and prefix_length else network,
            "metric": _pick(row, "metric") or None,
        }
        if not hops:
            routes.append(
                {**base, "next_hop": "", "interface": interfaces[0] if interfaces else ""}
            )
            continue
        for index, hop in enumerate(hops):
            # Arista lists next hops and interfaces side by side; otherwise one interface applies.
            if len(interfaces) == len(hops):
                interface = interfaces[index]
            else:
                interface = interfaces[0] if interfaces else ""
            routes.append({**base, "next_hop": _ip_or_empty(hop), "interface": interface})
    return routes


def aggregate_routes(routes: Sequence[Record], step: Step) -> tuple[list[Record], Record]:
    """Routes grouped by ``(protocol, next hop, interface)``, with counts and a few examples.

    A routing table is large: the records say which next hops carry how many routes of which
    protocol, the full list stays with the caller. The summary always reports the number of routes
    per protocol and the default route.
    """
    groups: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    per_protocol: dict[str, int] = defaultdict(int)
    default_route: Record | None = None
    for route in routes:
        per_protocol[route["protocol"]] += 1
        if route["prefix"] in _DEFAULT_PREFIXES and route["next_hop"]:
            default_route = default_route or {
                "next_hop": route["next_hop"],
                "interface": route["interface"],
                "protocol": route["protocol"],
            }
        if route["protocol"] in _NO_NEIGHBOR or not route["next_hop"]:
            continue
        groups[(route["protocol"], route["next_hop"], route["interface"])].append(route)
    records = [
        {
            "layer": "l3",
            "protocol": "routing_table",
            "vrf": step.vrf,
            "route_protocol": protocol,
            "next_hop": next_hop,
            "interface": interface,
            "route_count": len(items),
            "example_prefixes": [i["prefix"] for i in items[:MAX_EXAMPLE_PREFIXES]],
        }
        for (protocol, next_hop, interface), items in sorted(groups.items())
    ]
    summary = {
        "routes_per_protocol": dict(sorted(per_protocol.items())),
        "default_route": default_route,
    }
    return records, summary


def normalize_rows(step: Step, rows: Sequence[Row]) -> list[Record]:
    """Neighbour records for the rows one catalogued command returned.

    A routing table is aggregated here (``aggregate_routes``); every other table gives one record
    per row. A row that names no usable peer is left out rather than invented.
    """
    if step.layer == "l2":
        records = [_l2_record(step.protocol, row) for row in rows]
        return [r for r in records if r["local_interface"] or r["neighbor_name"]]
    if step.protocol == "routing_table":
        return aggregate_routes(_route_rows(rows, step), step)[0]
    builders = {
        "ospf": _ospf_record,
        "bgp": _bgp_record,
    }
    records = [
        builders[step.protocol](row, step)
        if step.protocol in builders
        else _simple_adjacency(step.protocol, row, step)
        for row in rows
    ]
    return [r for r in records if r is not None]


def routing_summary(step: Step, rows: Sequence[Row]) -> Record:
    """Counts per protocol and the default route of a routing-table command's rows."""
    return aggregate_routes(_route_rows(rows, step), step)[1]


def canonical_local_interface(record: Record) -> str:
    """The canonical local interface of a record, for comparisons."""
    return canonical_interface_name(
        str(record.get("local_interface") or record.get("interface") or "")
    )
