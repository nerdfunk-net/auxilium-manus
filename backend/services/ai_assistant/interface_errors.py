"""Interface error and drop counters from parsed ``show interfaces`` rows (AI_TOOL_CHAIN.md §54).

Pure functions over the rows TextFSM produced (one dict per interface, string values). The
counters that count are an explicit allow-list in two groups, not a name pattern: a pattern on
"error" would miss ``crc``, ``frame``, ``overrun``, ``abort``, ``runts``, ``giants`` and the queue
drops, and a template of another platform may name unrelated columns alike. Nothing here reads a
device, the store or the network, and no input row is changed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Error counters. ``input_errors`` already includes ``crc``, ``frame`` and ``overrun`` on IOS, so
# the counters are reported one by one and never added into a total. The first eight are the IOS
# and IOS-XR template columns; the last four are NX-OS columns (``cisco_nxos_show_interface``),
# where ``stomped_crc`` and ``short_frame`` are the usual signals and not part of ``input_errors``.
ERROR_COUNTERS: tuple[str, ...] = (
    "input_errors",
    "output_errors",
    "crc",
    "frame",
    "overrun",
    "abort",
    "runts",
    "giants",
    "stomped_crc",
    "short_frame",
    "underrun",
    "late_collisions",
)
# Packets dropped or discarded: the IOS queue counters, then the NX-OS columns.
DROP_COUNTERS: tuple[str, ...] = (
    "queue_drops",
    "queue_output_drops",
    "input_discards",
    "output_discards",
    "ignored",
    "bad_etype_drop",
    "bad_proto_drop",
    "interface_down_drop",
)
ALL_COUNTERS: tuple[str, ...] = ERROR_COUNTERS + DROP_COUNTERS

_RATE_DECIMALS = 6
_MIN_ABBREVIATION_LETTERS = 2
_NAME_PARTS = re.compile(r"([A-Za-z][A-Za-z-]*?)(\d[\d/.:]*)")


def counter_value(raw: Any) -> int | None:
    """A counter as an integer; ``None`` when the template left it empty or it is not a number.

    TextFSM gives strings, and an empty string means "this platform does not report it", which
    must never be read as zero.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.isascii() and text.isdigit():
            return int(text)
    return None


def is_interface_row(row: Mapping[str, Any]) -> bool:
    name = row.get("interface")
    return isinstance(name, str) and name.strip() != ""


def interface_matches(name: str, wanted: str) -> bool:
    """Whether ``wanted`` names the interface ``name``: the full name, or an abbreviation of it.

    ``Gi0/1`` matches ``GigabitEthernet0/1`` (the letters are a prefix, the numbers are equal) and
    its subinterfaces (``GigabitEthernet0/1.100``), but not ``GigabitEthernet0/10``. A name that
    already has a subinterface number (``Gi0/1.100``) matches only that one. Case is ignored. An
    abbreviation needs at least two letters; ``interface_type_clash`` finds the case where it fits
    more than one type of interface.
    """
    wanted = wanted.strip()
    if not wanted:
        return False
    if name.casefold() == wanted.casefold():
        return True
    have, ask = _NAME_PARTS.fullmatch(name.strip()), _NAME_PARTS.fullmatch(wanted)
    if have is None or ask is None or len(ask.group(1)) < _MIN_ABBREVIATION_LETTERS:
        return False
    if not have.group(1).casefold().startswith(ask.group(1).casefold()):
        return False
    have_number, ask_number = have.group(2), ask.group(2)
    return have_number == ask_number or (
        "." not in ask_number and have_number.startswith(f"{ask_number}.")
    )


def interface_type_clash(names: Iterable[str], wanted: str) -> tuple[str, ...]:
    """The matched names when ``wanted`` is an abbreviation that fits more than one interface type.

    ``Se0/1`` fits ``Serial0/1`` and ``Service-Engine0/1``, ``Po1`` fits ``Port-channel1`` and
    ``Port1``: answering for both would put one interface's errors under the other's name. A full
    name (some interface has exactly that name) is never a clash. Empty when there is none.
    """
    matched = [n for n in names if interface_matches(n, wanted)]
    if any(n.casefold() == wanted.strip().casefold() for n in matched):
        return ()
    types = {m.group(1).casefold() for n in matched if (m := _NAME_PARTS.fullmatch(n.strip()))}
    return tuple(matched) if len(types) > 1 else ()


@dataclass(frozen=True)
class ErrorSummary:
    """What the rows say; ``findings`` are the interfaces worth reporting, worst first."""

    findings: tuple[dict[str, Any], ...]
    interfaces_in_output: int
    interfaces_checked: int
    interfaces_with_errors: int
    interfaces_with_drops: int
    interfaces_with_problems: int
    counter_totals: dict[str, int]
    counters_looked_at: tuple[str, ...]
    counters_not_in_output: tuple[str, ...]
    unparsed: int
    # Set when ``interface`` is an abbreviation of more than one interface type; nothing is checked.
    ambiguous: tuple[str, ...] = ()

    @property
    def errors_checked(self) -> bool:
        """Whether the template had any error counter, so errors were really looked at."""
        return any(c in self.counters_looked_at for c in ERROR_COUNTERS)

    @property
    def drops_checked(self) -> bool:
        """Whether the template had any drop counter (IOS-XR has none), so drops were looked at."""
        return any(c in self.counters_looked_at for c in DROP_COUNTERS)


def _nonzero(values: Mapping[str, int | None], names: Iterable[str]) -> dict[str, int]:
    return {n: v for n in names if (v := values.get(n)) is not None and v > 0}


def _percent(count: int | None, packets: int | None) -> float | None:
    if not count or not packets:
        return None
    return round(count / packets * 100, _RATE_DECIMALS)


def _rates(values: Mapping[str, int | None]) -> dict[str, float]:
    """Counter / packets in percent, for the four ratios that can be measured.

    ``input_errors`` is measured against the input packets (a few errors on a busy link are noise,
    on a quiet one they are not), the output counters against the output packets.
    """
    in_packets, out_packets = values.get("input_packets"), values.get("output_packets")
    pairs = {
        "input_errors_percent": (values.get("input_errors"), in_packets),
        "output_errors_percent": (values.get("output_errors"), out_packets),
        "input_drops_percent": (
            values.get("queue_drops") or values.get("input_discards"),
            in_packets,
        ),
        "output_drops_percent": (
            values.get("queue_output_drops") or values.get("output_discards"),
            out_packets,
        ),
    }
    return {key: p for key, (n, pk) in pairs.items() if (p := _percent(n, pk)) is not None}


def _finding(row: Mapping[str, Any], values: Mapping[str, int | None]) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "interface": str(row["interface"]).strip(),
        "link_status": str(row.get("link_status") or ""),
        "protocol_status": str(row.get("protocol_status") or ""),
        "errors": _nonzero(values, ERROR_COUNTERS),
        "drops": _nonzero(values, DROP_COUNTERS),
        "input_packets": values.get("input_packets"),
        "output_packets": values.get("output_packets"),
    }
    description = str(row.get("description") or "").strip()
    if description:
        finding["description"] = description
    rates = _rates(values)
    if rates:
        finding["rates_percent"] = rates
    return finding


def _values_of(row: Mapping[str, Any]) -> dict[str, int | None]:
    keys = (*ALL_COUNTERS, "input_packets", "output_packets")
    return {key: counter_value(row.get(key)) for key in keys}


def _severity(finding: Mapping[str, Any]) -> int:
    """Sort key only: the largest single counter of the interface.

    Counters are not added: ``input_errors`` already contains ``crc``, so a sum would rank an
    interface on a number that counts the same packets twice.
    """
    return max([*finding["errors"].values(), *finding["drops"].values(), 0])


def summarize_interface_errors(
    rows: Sequence[Mapping[str, Any]], *, interface: str | None = None
) -> ErrorSummary:
    """Condense parsed interface rows into the interfaces that have non-zero error counters.

    With ``interface`` only the interfaces it names are looked at, and they are all reported, also
    the clean ones, because the question was about them. Rows that are not interface rows (a
    command that did not parse, another command's rows) are not counted as interfaces.
    """
    interface_rows = [r for r in rows if is_interface_row(r)]
    unparsed = sum(1 for r in rows if "_error" in r and not is_interface_row(r))
    if interface is not None:
        clash = interface_type_clash([r["interface"] for r in interface_rows], interface)
        if clash:
            return ErrorSummary(
                findings=(),
                interfaces_in_output=len(interface_rows),
                interfaces_checked=0,
                interfaces_with_errors=0,
                interfaces_with_drops=0,
                interfaces_with_problems=0,
                counter_totals={},
                counters_looked_at=(),
                counters_not_in_output=ALL_COUNTERS,
                unparsed=unparsed,
                ambiguous=clash,
            )
    checked = [
        r
        for r in interface_rows
        if interface is None or interface_matches(r["interface"], interface)
    ]
    looked_at: set[str] = set()
    totals: dict[str, int] = {}
    findings: list[dict[str, Any]] = []
    for row in checked:
        values = _values_of(row)
        looked_at.update(k for k in ALL_COUNTERS if values[k] is not None)
        finding = _finding(row, values)
        for counter, count in {**finding["errors"], **finding["drops"]}.items():
            totals[counter] = totals.get(counter, 0) + count
        if interface is not None or finding["errors"] or finding["drops"]:
            findings.append(finding)
    findings.sort(key=lambda f: (-_severity(f), f["interface"].casefold()))
    problems = [f for f in findings if f["errors"] or f["drops"]]
    return ErrorSummary(
        findings=tuple(findings),
        interfaces_in_output=len(interface_rows),
        interfaces_checked=len(checked),
        interfaces_with_errors=sum(1 for f in problems if f["errors"]),
        interfaces_with_drops=sum(1 for f in problems if f["drops"]),
        interfaces_with_problems=len(problems),
        counter_totals=totals,
        counters_looked_at=tuple(k for k in ALL_COUNTERS if k in looked_at),
        counters_not_in_output=tuple(k for k in ALL_COUNTERS if k not in looked_at),
        unparsed=unparsed,
    )
