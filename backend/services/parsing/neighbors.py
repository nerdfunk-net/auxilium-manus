"""Reading the output of a CDP / LLDP neighbour command (pure, no I/O).

Netmiko returns a command's TextFSM result as a JSON string when a template matched and as the
raw device text otherwise. ``discover-network`` and ``collect-client-data`` both have to decide
what such an output is: a table (rows), an empty table, a refusal by the device, a protocol that
is switched off, or something that is none of those. They share this decision and the reading of
a row's columns (``neighbor_fields``, also used by the Ask the Net neighbour reader); each keeps its
own status vocabulary and its own sanitising.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from services.network.netmiko.output_check import find_cli_error

# The device types the neighbour commands and the TextFSM templates are catalogued for.
SUPPORTED_CISCO_DEVICE_TYPES = frozenset({"cisco_ios", "cisco_xe", "cisco_nxos"})

# Only an explicit "0 entries" line is an empty table. Blank output is not: a dropped session
# prints nothing too, and "no neighbours" would end a walk or replace the stored neighbours.
ZERO_ENTRIES = re.compile(r"total (?:cdp )?entries displayed\s*:\s*0\b", re.IGNORECASE)
# The protocol is switched off on the device: the table is missing, not empty.
PROTOCOL_OFF = re.compile(
    r"\b(?:lldp|cdp)\b[^\n]*\bnot (?:enabled|running|active)\b"
    r"|\bnot (?:enabled|running)\b[^\n]*\b(?:lldp|cdp)\b",
    re.IGNORECASE,
)


# Characters that make a value blank for the column choice (control and invisible characters).
_INVISIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\ufeff]")

# The TextFSM columns of a neighbour row, first non-blank wins (ntc-templates differ per platform
# and protocol). On IOS LLDP ``neighbor_interface`` is the neighbour's port *description* and
# ``neighbor_port_id`` the port, so the port id comes first; NX-OS CDP has ``interface_ip``.
_NAME = ("neighbor_name", "neighbor")
_REMOTE_PORT = ("neighbor_port_id", "neighbor_interface")
_ADDRESS = ("mgmt_address", "management_ip", "interface_ip")


@dataclass(frozen=True)
class NeighborFields:
    """The columns of one CDP / LLDP neighbour row as text ("" when absent), not yet sanitised."""

    name: str
    local_interface: str
    remote_port: str
    address: str
    platform: str
    capabilities: str
    description: str


def _column(row: Mapping[str, Any], *names: str) -> str:
    """The first column among ``names`` that is not blank; a list column gives its first item."""
    for name in names:
        value = row.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            continue
        text = str(value)
        if _INVISIBLE.sub("", text).strip():
            return text
    return ""


def neighbor_fields(row: Mapping[str, Any]) -> NeighborFields:
    """One neighbour row read in the shared column order (W3b-08)."""
    return NeighborFields(
        name=_column(row, *_NAME),
        local_interface=_column(row, "local_interface"),
        remote_port=_column(row, *_REMOTE_PORT),
        address=_column(row, *_ADDRESS),
        platform=_column(row, "platform"),
        capabilities=_column(row, "capabilities"),
        description=_column(row, "neighbor_description"),
    )


class TableKind(StrEnum):
    ROWS = "rows"  # a TextFSM table (possibly with no rows)
    EMPTY = "empty"  # raw text that says "0 entries"
    REFUSED = "refused"  # the device rejected the command
    PROTOCOL_OFF = "protocol_off"
    UNPARSEABLE = "unparseable"  # blank, or text that is none of the above


@dataclass(frozen=True)
class NeighborTable:
    kind: TableKind
    rows: list[dict[str, Any]] = field(default_factory=list)


def decode_textfsm_output(raw: str) -> list[dict[str, Any]] | None:
    """The rows of a TextFSM result, or ``None`` when ``raw`` is not a JSON list of rows."""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, list) or not all(isinstance(row, dict) for row in decoded):
        return None
    return decoded


def classify_neighbor_table(raw: str) -> NeighborTable:
    """What one neighbour command printed.

    Blank or unrecognised output is ``UNPARSEABLE`` and never "no neighbours".
    """
    if not raw or not raw.strip():
        return NeighborTable(TableKind.UNPARSEABLE)
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        if find_cli_error(raw) is not None:
            return NeighborTable(TableKind.REFUSED)
        if PROTOCOL_OFF.search(raw):
            return NeighborTable(TableKind.PROTOCOL_OFF)
        if ZERO_ENTRIES.search(raw):
            return NeighborTable(TableKind.EMPTY)
        return NeighborTable(TableKind.UNPARSEABLE)
    rows = decode_textfsm_output(raw)
    if rows is None:
        return NeighborTable(TableKind.UNPARSEABLE)
    return NeighborTable(TableKind.ROWS, rows)
