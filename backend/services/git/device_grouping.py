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
    MappingRule,
    apply_device_mapping,
    apply_interface_mapping,
    resolve_source_value,
)


@dataclass(frozen=True)
class GroupedEntry:
    """A device: merged raw cells (``raw``) and its Nautobot-shaped form (``mapped``)."""

    raw: dict[str, Any]
    mapped: dict[str, Any]


def map_single_row(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> dict[str, Any] | None:
    """Map one row to a device; an interface on the same row becomes a one-item list."""
    device = apply_device_mapping(entry, rules)
    if device is None:
        return None
    interface = apply_interface_mapping(entry, rules)
    return {**device, "interfaces": [interface]} if interface else device


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
        raw_by_name[key] = {**raw_by_name[key], **_non_empty(row)}
        mapped_by_name[key] = _deep_overwrite(mapped_by_name[key], device_part)
        if interface:
            interfaces_by_name[key] = [*interfaces_by_name[key], interface]

    groups = [
        GroupedEntry(
            raw=raw_by_name[key],
            mapped=(
                {**mapped_by_name[key], "interfaces": interfaces_by_name[key]}
                if interfaces_by_name[key]
                else mapped_by_name[key]
            ),
        )
        for key in order
    ]
    warnings: list[str] = []
    if nameless:
        warnings.append(
            f"{nameless} line{'s' if nameless != 1 else ''} skipped: "
            f"no value in the column mapped to Device name ('{name_source}')"
        )
    return groups, warnings
