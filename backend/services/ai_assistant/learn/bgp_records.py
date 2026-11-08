"""Genie output of a BGP learn -> one record per neighbour and address family. Pure functions.

doc/plans/BGP_PLAYBOOK.md step 3 (option A). The shapes are those of the Genie parsers
``ShowBgpAllSummary`` and ``ShowBgpAllNeighbors`` (``genie.libs.parser.iosxe.show_bgp``), read from
the installed source, not from a router run:

* summary:   ``{"bgp_id", "vrf": {vrf: {"neighbor": {ip: {"address_family": {af: {...}}}}}}}``
* neighbors: ``{"vrf": {vrf: {"neighbor": {ip: {"remote_as", "link", "session_state", ...}}}}}``

Everything is read defensively: a missing or oddly shaped key gives ``None``, never an exception.
Text that came from the configuration (descriptions) is stripped of control characters and cut,
and only ever returned as a data field.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

MAX_TEXT_CHARS = 100
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮﻿]")
_SUMMARY = re.compile(r"show (?:ip )?bgp (?:vrf \S+ )?all summary", re.IGNORECASE)
# ``show bgp all neighbors`` and, for a VRF, ``show bgp ipv4 unicast vrf <v> neighbors`` (the form
# Genie registers; there is no ``show bgp vrf <v> all neighbors`` parser).
_NEIGHBORS = re.compile(
    r"show (?:ip )?bgp (?:all|(?:ipv4|ipv6) unicast vrf \S+) neighbors", re.IGNORECASE
)
_STATE_WORDS = {
    "idle": "Idle",
    "active": "Active",
    "connect": "Connect",
    "opensent": "OpenSent",
    "openconfirm": "OpenConfirm",
}
# Every record has all of these keys (``None`` when its command did not say), so a table built from
# them has the same columns in every row.
_SUMMARY_KEYS = (
    "remote_as",
    "state",
    "prefixes_received",
    "up_down",
    "messages_received",
    "messages_sent",
)
_DETAIL_KEYS = (
    "remote_as",
    "type",
    "session_state",
    "shutdown",
    "description",
    "peer_group",
    "neighbor_router_id",
    "hold_time",
    "keepalive",
    "last_reset",
    "reset_reason",
    "times_established",
    "times_dropped",
)

Record = dict[str, Any]


class Entry(Protocol):
    """What the parse step returns per command (``output_parser.ParsedCommand``)."""

    command: str
    parsed: Any
    error: str | None


def is_summary_command(command: str) -> bool:
    return bool(_SUMMARY.fullmatch(command.strip()))


def is_neighbors_command(command: str) -> bool:
    return bool(_NEIGHBORS.fullmatch(command.strip()))


def _dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    cleaned = _CONTROL.sub(" ", str(value)).strip()
    return cleaned[:MAX_TEXT_CHARS] or None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _state(pfxrcd: Any) -> tuple[str | None, int | None]:
    """``(state, prefixes received)`` from the last column of the summary.

    A number means Established with that many prefixes; a word is the state itself.
    """
    word = _text(pfxrcd)
    if word is None:
        return None, None
    if word.isdigit():
        return "Established", int(word)
    return _STATE_WORDS.get(word.lower(), word), None


def _summary_index(parsed: Any) -> tuple[dict[tuple[str, str, str], Record], Record]:
    """Per ``(vrf, neighbor, address family)`` the summary fields, and the global ones."""
    index: dict[tuple[str, str, str], Record] = {}
    meta: Record = {"local_as": _text(_dict(parsed).get("bgp_id")), "router_ids": []}
    for vrf, vrf_data in _dict(_dict(parsed).get("vrf")).items():
        for ip, peer in _dict(_dict(vrf_data).get("neighbor")).items():
            for family, row in _dict(_dict(peer).get("address_family")).items():
                row = _dict(row)
                state, received = _state(row.get("state_pfxrcd"))
                index[(str(vrf), str(ip), str(family).lower())] = {
                    "remote_as": _text(row.get("as")),
                    "state": state,
                    "prefixes_received": received,
                    "up_down": _text(row.get("up_down")),
                    "messages_received": _int(row.get("msg_rcvd")),
                    "messages_sent": _int(row.get("msg_sent")),
                }
                router_id = _text(row.get("route_identifier"))
                if router_id and router_id not in meta["router_ids"]:
                    meta["router_ids"].append(router_id)
    return index, meta


def _neighbor_fields(peer: Mapping[str, Any]) -> Record:
    timers = _dict(peer.get("bgp_negotiated_keepalive_timers"))
    connection = _dict(_dict(peer.get("bgp_session_transport")).get("connection"))
    return {
        "remote_as": _text(peer.get("remote_as")),
        "type": _text(peer.get("link")),
        "session_state": _text(peer.get("session_state")),
        "shutdown": peer.get("shutdown") if isinstance(peer.get("shutdown"), bool) else None,
        "description": _text(peer.get("description")),
        "peer_group": _text(peer.get("peer_group")),
        "neighbor_router_id": _text(peer.get("router_id")),
        "hold_time": _int(timers.get("hold_time")),
        "keepalive": _int(timers.get("keepalive_interval")),
        "last_reset": _text(connection.get("last_reset")),
        "reset_reason": _text(connection.get("reset_reason")),
        "times_established": _int(connection.get("established")),
        "times_dropped": _int(connection.get("dropped")),
    }


def _neighbors_index(parsed: Any) -> dict[tuple[str, str], tuple[Record, list[str]]]:
    """Per ``(vrf, neighbor)`` the session fields and the address families it is configured for."""
    index: dict[tuple[str, str], tuple[Record, list[str]]] = {}
    for vrf, vrf_data in _dict(_dict(parsed).get("vrf")).items():
        for ip, peer in _dict(_dict(vrf_data).get("neighbor")).items():
            families = [str(f).lower() for f in _dict(_dict(peer).get("address_family"))]
            index[(str(vrf), str(ip))] = (_neighbor_fields(_dict(peer)), families)
    return index


def _row(summary: Mapping[str, Any], detail: Mapping[str, Any]) -> Record:
    """All summary and detail keys; the summary wins for ``remote_as``, the detail fills gaps."""
    row: Record = {k: None for k in (*_SUMMARY_KEYS, *_DETAIL_KEYS)}
    row.update({k: v for k, v in detail.items() if k in row})
    row.update({k: v for k, v in summary.items() if k in row and v is not None})
    return row


def summarize_bgp(entries: Sequence[Entry]) -> tuple[Record, list[Record], list[dict[str, str]]]:
    """``(global facts, neighbour records, errors)`` of the summary and neighbors commands.

    A command that did not parse is listed under ``errors`` and contributes nothing; the facts of
    the other command are still returned, so the answer can say which half is missing.
    """
    summary_index: dict[tuple[str, str, str], Record] = {}
    neighbors_index: dict[tuple[str, str], tuple[Record, list[str]]] = {}
    facts: Record = {"local_as": None, "router_ids": []}
    errors: list[dict[str, str]] = []
    for entry in entries:
        summary, detail = is_summary_command(entry.command), is_neighbors_command(entry.command)
        if not (summary or detail):
            continue
        if entry.error is not None or not isinstance(entry.parsed, Mapping):
            errors.append({"command": entry.command, "error": entry.error or "no data"})
        elif summary:
            found, meta = _summary_index(entry.parsed)
            summary_index = {**summary_index, **found}
            facts = {
                "local_as": facts["local_as"] or meta["local_as"],
                "router_ids": [*facts["router_ids"], *meta["router_ids"]],
            }
        else:
            neighbors_index = {**neighbors_index, **_neighbors_index(entry.parsed)}
    return facts, _records(summary_index, neighbors_index), errors


def _records(
    summary_index: Mapping[tuple[str, str, str], Record],
    neighbors_index: Mapping[tuple[str, str], tuple[Record, list[str]]],
) -> list[Record]:
    records: list[Record] = []
    seen: set[tuple[str, str, str]] = set()
    for (vrf, ip, family), row in summary_index.items():
        detail = neighbors_index.get((vrf, ip), ({}, []))[0]
        records.append({"vrf": vrf, "neighbor": ip, "address_family": family, **_row(row, detail)})
        seen.add((vrf, ip, family))
    for (vrf, ip), (detail, families) in neighbors_index.items():
        # An address family only the neighbors output knows (not in the summary yet, or shut) still
        # gets a row, with the summary fields empty.
        for family in families or [""]:
            if (vrf, ip, family) in seen:
                continue
            records.append(
                {"vrf": vrf, "neighbor": ip, "address_family": family or None, **_row({}, detail)}
            )
    return sorted(records, key=lambda r: (r["vrf"], r["neighbor"], r["address_family"] or ""))
