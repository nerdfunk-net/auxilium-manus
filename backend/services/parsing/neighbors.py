"""Reading the output of a CDP / LLDP neighbour command (pure, no I/O).

Netmiko returns a command's TextFSM result as a JSON string when a template matched and as the
raw device text otherwise. ``discover-network`` and ``collect-client-data`` both have to decide
what such an output is: a table (rows), an empty table, a refusal by the device, a protocol that
is switched off, or something that is none of those. They share this decision; each keeps its own
status vocabulary and its own row mapping (the steps read different fields and sanitise
differently).
"""

from __future__ import annotations

import json
import re
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
