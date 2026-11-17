"""Traffic rate against capacity from parsed ``show interfaces`` rows (AI_TOOL_CHAIN.md §56).

Pure functions over the rows TextFSM produced (one dict per row, string values, the command in
``_command``). The rates are the device's 5-minute average (``load-interval``), the capacity is the
interface's ``BW`` (the ``bandwidth`` command, not necessarily the link speed). A neighbour table
of the same handle (``show cdp neighbors`` or ``show lldp neighbors``) marks the ports that have a
neighbour, which is how an uplink or downlink is told. Nothing here reads a device, the store or
the network, and no input row is changed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from services.ai_assistant.interface_errors import (
    interface_matches,
    interface_type_clash,
    is_interface_row,
)
from services.network.interface_names import canonical_interface_name

OnlyFilter = Literal["all", "neighbor_facing"]
SortBy = Literal["peak", "input", "output"]
NeighborData = Literal["available", "command_failed", "not_in_handle"]

# Template columns, first one present wins: IOS / IOS-XR, then NX-OS.
RATE_IN_COLUMNS: tuple[str, ...] = ("input_rate", "bandwidth_input_rate")
RATE_OUT_COLUMNS: tuple[str, ...] = ("output_rate", "bandwidth_output_rate")
PPS_IN_COLUMNS: tuple[str, ...] = ("input_pps", "packet_input_rate")
PPS_OUT_COLUMNS: tuple[str, ...] = ("output_pps", "packet_output_rate")
RATE_COLUMNS: tuple[str, ...] = RATE_IN_COLUMNS + RATE_OUT_COLUMNS

_NEIGHBOR_COMMANDS = ("show cdp neighbor", "show lldp neighbor")
_PERCENT_DECIMALS = 2
_PREFIX = {"k": 10**3, "m": 10**6, "g": 10**9, "t": 10**12}
_BPS = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<prefix>[kmgt])?(?:bits?|b)?(?:/s(?:ec)?|ps)?",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"\d+")
_UNITS = ((10**9, "Gbit/s"), (10**6, "Mbit/s"), (10**3, "kbit/s"))


def parse_bps(raw: Any, *, default_prefix: str = "") -> int | None:
    """A rate or capacity as bits per second; ``None`` when empty or not a number.

    ``"1000000 Kbit"`` (the ``BW`` of a template), ``"1000Mb/s"`` (a speed), ``"30000 bits/sec"``
    and a bare ``"5000000"`` are read. A bare number takes ``default_prefix`` (``"k"`` for a ``BW``,
    which is in kilobits, ``""`` for a rate, which is in bits). Empty is never zero.
    """
    if not isinstance(raw, str) or isinstance(raw, bool):
        return None
    text = raw.strip()
    if not text.isascii():
        return None
    found = _BPS.fullmatch(text)
    if found is None:
        return None
    prefix = found.group("prefix")
    if prefix is None and _BARE_NUMBER.fullmatch(text):
        prefix = default_prefix or None
    multiplier = _PREFIX[prefix.lower()] if prefix else 1
    return round(float(found.group("number")) * multiplier)


def format_bps(bps: int) -> str:
    """``1500000`` as ``"1.5 Mbit/s"``."""
    for size, unit in _UNITS:
        if bps >= size:
            number = f"{bps / size:.1f}".rstrip("0").rstrip(".")
            return f"{number} {unit}"
    return f"{bps} bit/s"


def _first(row: Mapping[str, Any], columns: Sequence[str]) -> Any:
    return next((row[c] for c in columns if c in row), None)


def has_rate_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the template of any interface row has a rate column (empty values count)."""
    return any(c in r for r in rows if is_interface_row(r) for c in RATE_COLUMNS)


def _capacity(row: Mapping[str, Any]) -> int | None:
    for column, prefix in (("bandwidth", "k"), ("speed", "m")):
        value = parse_bps(row.get(column), default_prefix=prefix)
        if value:
            return value
    return None


def _percent(rate: int | None, capacity: int | None) -> float | None:
    if rate is None or not capacity:
        return None
    return round(rate / capacity * 100, _PERCENT_DECIMALS)


def _is_neighbor_command(command: Any) -> bool:
    return isinstance(command, str) and command.strip().casefold().startswith(_NEIGHBOR_COMMANDS)


def _neighbor_entry(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": str(row.get("neighbor_name") or "").strip(),
        "platform": str(row.get("platform") or "").strip(),
        "capabilities": str(row.get("capabilities") or "").strip(),
        "port": str(row.get("neighbor_interface") or "").strip(),
    }


def neighbors_by_port(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """CDP / LLDP neighbours keyed by the lower-case canonical name of the local port."""
    found: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        local = r.get("local_interface")
        if _is_neighbor_command(r.get("_command")) and isinstance(local, str) and local.strip():
            key = canonical_interface_name(local).casefold()
            found.setdefault(key, []).append(_neighbor_entry(r))
    return found


def _neighbor_data(rows: Sequence[Mapping[str, Any]], known: Mapping[str, Any]) -> NeighborData:
    if known:
        return "available"
    failed = any("_error" in r and _is_neighbor_command(r.get("_command")) for r in rows)
    return "command_failed" if failed else "not_in_handle"


@dataclass(frozen=True)
class UtilizationSummary:
    """What the rows say; ``findings`` are the checked interfaces, busiest first."""

    findings: tuple[dict[str, Any], ...]
    interfaces_in_output: int
    interfaces_checked: int
    interfaces_without_rates: int
    interfaces_without_capacity: int
    busiest: dict[str, Any] | None
    neighbor_data: NeighborData
    # Commands other than the neighbour table that did not parse.
    unparsed: int
    # Set when ``interface`` is an abbreviation of more than one interface type; nothing is checked.
    ambiguous: tuple[str, ...] = ()


def _finding(
    row: Mapping[str, Any], neighbors: Mapping[str, list[dict[str, str]]]
) -> dict[str, Any]:
    rate_in = parse_bps(_first(row, RATE_IN_COLUMNS))
    rate_out = parse_bps(_first(row, RATE_OUT_COLUMNS))
    capacity = _capacity(row)
    util_in, util_out = _percent(rate_in, capacity), _percent(rate_out, capacity)
    known = [u for u in (util_in, util_out) if u is not None]
    name = str(row["interface"]).strip()
    finding: dict[str, Any] = {
        "interface": name,
        "link_status": str(row.get("link_status") or ""),
        "protocol_status": str(row.get("protocol_status") or ""),
        "capacity": format_bps(capacity) if capacity else None,
        "rate_in": format_bps(rate_in) if rate_in is not None else None,
        "rate_out": format_bps(rate_out) if rate_out is not None else None,
        "utilization_in_percent": util_in,
        "utilization_out_percent": util_out,
        "peak_percent": max(known) if known else None,
        "rate_in_bps": rate_in,
        "rate_out_bps": rate_out,
    }
    description = str(row.get("description") or "").strip()
    if description:
        finding["description"] = description
    for key, columns in (("pps_in", PPS_IN_COLUMNS), ("pps_out", PPS_OUT_COLUMNS)):
        pps = parse_bps(_first(row, columns))
        if pps is not None:
            finding[key] = pps
    attached = neighbors.get(canonical_interface_name(name).casefold())
    if attached:
        finding["neighbors"] = [dict(n) for n in attached]
    return finding


_SORT_FIELDS: dict[str, str] = {
    "peak": "peak_percent",
    "input": "utilization_in_percent",
    "output": "utilization_out_percent",
}


def _sort_value(finding: Mapping[str, Any], sort_by: SortBy) -> float | None:
    return finding[_SORT_FIELDS[sort_by]]


def _sorted(findings: list[dict[str, Any]], sort_by: SortBy) -> list[dict[str, Any]]:
    """Busiest first; an interface whose percentage is unknown goes last, never first."""

    def key(f: Mapping[str, Any]) -> tuple[bool, float, str]:
        value = _sort_value(f, sort_by)
        return (value is None, -(value or 0.0), f["interface"].casefold())

    return sorted(findings, key=key)


def summarize_utilization(
    rows: Sequence[Mapping[str, Any]],
    *,
    interface: str | None = None,
    only: OnlyFilter = "all",
    sort_by: SortBy = "peak",
) -> UtilizationSummary:
    """Condense parsed interface rows into traffic figures, busiest first.

    With ``interface`` only the interfaces it names are looked at. With ``only="neighbor_facing"``
    only ports that have a CDP or LLDP neighbour in the same rows are kept; when the rows hold no
    neighbour table nothing is kept and ``neighbor_data`` says why, so the caller never reads
    "no neighbours" out of a missing table.
    """
    interface_rows = [r for r in rows if is_interface_row(r)]
    unparsed = sum(
        1
        for r in rows
        if "_error" in r and not is_interface_row(r) and not _is_neighbor_command(r.get("_command"))
    )
    neighbors = neighbors_by_port(rows)
    neighbor_data = _neighbor_data(rows, neighbors)
    clash = (
        interface_type_clash([r["interface"] for r in interface_rows], interface)
        if interface is not None
        else ()
    )
    candidates = [
        r
        for r in interface_rows
        if not clash and (interface is None or interface_matches(r["interface"], interface))
    ]
    findings = [_finding(r, neighbors) for r in candidates]
    if only == "neighbor_facing":
        findings = [f for f in findings if "neighbors" in f]
    ordered = _sorted(findings, sort_by)
    field = _SORT_FIELDS[sort_by]
    measured = next((f for f in ordered if f[field] is not None), None)
    return UtilizationSummary(
        findings=tuple(ordered),
        interfaces_in_output=len(interface_rows),
        interfaces_checked=len(ordered),
        interfaces_without_rates=sum(
            1 for f in ordered if f["rate_in"] is None and f["rate_out"] is None
        ),
        interfaces_without_capacity=sum(1 for f in ordered if f["capacity"] is None),
        busiest=(
            {"interface": measured["interface"], "percent": measured[field], "by": field}
            if measured
            else None
        ),
        neighbor_data=neighbor_data,
        unparsed=unparsed,
        ambiguous=clash,
    )
