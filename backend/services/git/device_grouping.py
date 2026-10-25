"""Turn CSV rows into devices: one row per device, or several rows merged per device.

Pure functions. In the multi-line layout every row repeats the device name; rows carry either
device attributes (role, status, ...) or one interface. Rows with the same name are merged in
file order: a later non-empty value overwrites an earlier one, an empty value never erases.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.git.device_mapping import (
    NAME_TARGET,
    DeviceProblem,
    MappingRule,
    apply_device_mapping,
    apply_interface_mapping,
    primary_flag_source,
    read_primary_flag,
    resolve_primary_ip,
    resolve_source_value,
    safe_text,
)


@dataclass(frozen=True)
class GroupedEntry:
    """A device: merged raw cells (``raw``) and its Nautobot-shaped form (``mapped``)."""

    raw: dict[str, Any]
    mapped: dict[str, Any]
    # Data problems that fail this device (e.g. several interfaces flagged primary).
    problems: tuple[DeviceProblem, ...] = ()


def _flagged_interface(
    entry: Mapping[str, Any],
    rules: Sequence[MappingRule],
    interface: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[DeviceProblem]]:
    """The interface of a line flagged primary (``{}`` if the line has none), else ``None``."""
    flag = read_primary_flag(entry, rules)
    if flag is None:
        # The cell is deliberately not quoted: a shifted column can hold a secret.
        return None, [
            DeviceProblem(
                "invalid_primary_flag",
                f"column '{safe_text(primary_flag_source(rules))}' is neither true nor false",
            )
        ]
    return (interface or {} if flag else None), []


def _with_primary(
    mapped: dict[str, Any],
    flagged: Sequence[dict[str, Any]],
    flag_problems: Sequence[DeviceProblem] = (),
) -> tuple[dict[str, Any], tuple[DeviceProblem, ...]]:
    """Apply the flagged interface IP as ``primary_ip4``; a device with any problem gets none."""
    resolution = resolve_primary_ip(flagged)
    if resolution.primary_ip4 is None or flag_problems:
        return mapped, resolution.problems
    return {**mapped, "primary_ip4": resolution.primary_ip4}, resolution.problems


def map_single_row_with_problems(
    entry: Mapping[str, Any], rules: Sequence[MappingRule]
) -> tuple[dict[str, Any] | None, tuple[DeviceProblem, ...]]:
    """Map one row to a device; an interface on the same row becomes a one-item list.

    A row flagged primary makes its interface IP the device's ``primary_ip4``.
    """
    device = apply_device_mapping(entry, rules)
    if device is None:
        return None, ()
    interface = apply_interface_mapping(entry, rules)
    flagged, problems = _flagged_interface(entry, rules, interface)
    mapped, primary_problems = _with_primary(device, [] if flagged is None else [flagged], problems)
    if interface:
        mapped = {**mapped, "interfaces": [interface]}
    return mapped, (*problems, *primary_problems)


def map_single_row(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> dict[str, Any] | None:
    """:func:`map_single_row_with_problems` without the problems."""
    return map_single_row_with_problems(entry, rules)[0]


def _deep_overwrite(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        current = merged.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            merged[key] = _deep_overwrite(current, value)
        else:
            merged[key] = value
    return merged


def _non_empty(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if str(v).strip()}


def _group_key(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> str | None:
    for rule in rules:
        if rule.target == NAME_TARGET:
            value = resolve_source_value(entry, rule.source)
            text = "" if value is None else str(value).strip()
            return text or None
    return None


def merge_device_rows(
    rows: Iterable[Mapping[str, Any]], rules: Sequence[MappingRule]
) -> tuple[list[GroupedEntry], list[str]]:
    """Group ``rows`` by device name and merge them; returns ``(devices, warnings)``."""
    name_source = next((r.source for r in rules if r.target == NAME_TARGET), NAME_TARGET)
    order: list[str] = []
    raw_by_name: dict[str, dict[str, Any]] = {}
    mapped_by_name: dict[str, dict[str, Any]] = {}
    interfaces_by_name: dict[str, list[dict[str, Any]]] = {}
    flagged_by_name: dict[str, list[dict[str, Any]]] = {}
    problems_by_name: dict[str, list[DeviceProblem]] = {}
    nameless = 0

    for row in rows:
        key = _group_key(row, rules)
        if key is None:
            nameless += 1
            continue
        device_part = apply_device_mapping(row, rules) or {}
        interface = apply_interface_mapping(row, rules)
        if key not in raw_by_name:
            order.append(key)
            raw_by_name[key] = {}
            mapped_by_name[key] = {}
            interfaces_by_name[key] = []
            flagged_by_name[key] = []
            problems_by_name[key] = []
        raw_by_name[key] = {**raw_by_name[key], **_non_empty(row)}
        mapped_by_name[key] = _deep_overwrite(mapped_by_name[key], device_part)
        if interface:
            interfaces_by_name[key] = [*interfaces_by_name[key], interface]
        flagged, flag_problems = _flagged_interface(row, rules, interface)
        if flagged is not None:
            flagged_by_name[key] = [*flagged_by_name[key], flagged]
        problems_by_name[key] = [*problems_by_name[key], *flag_problems]

    groups: list[GroupedEntry] = []
    for key in order:
        mapped, primary_problems = _with_primary(
            mapped_by_name[key], flagged_by_name[key], problems_by_name[key]
        )
        if interfaces_by_name[key]:
            mapped = {**mapped, "interfaces": interfaces_by_name[key]}
        groups.append(
            GroupedEntry(
                raw=raw_by_name[key],
                mapped=mapped,
                problems=(*problems_by_name[key], *primary_problems),
            )
        )
    warnings: list[str] = []
    if nameless:
        warnings.append(
            f"{nameless} line{'s' if nameless != 1 else ''} skipped: "
            f"no value in the column mapped to Device name ('{name_source}')"
        )
    return groups, warnings
