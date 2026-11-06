"""Size cap for the step output that is persisted with a step result (C1-11).

Only the database copy is capped: the live context handed to the next step is untouched. A value
above the per-value limit is replaced by ``{"__truncated__": true, "bytes": N}``; when the whole
payload is still above the total limit, the largest remaining values are replaced until it fits.
"""

from __future__ import annotations

import json
from typing import Any

TRUNCATED_KEY = "__truncated__"


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))


def _marker(size: int) -> dict[str, Any]:
    return {TRUNCATED_KEY: True, "bytes": size}


def _is_marker(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get(TRUNCATED_KEY))


def _shrink(container: dict[str, Any], key: str, size: int, value_max: int) -> None:
    """Replace an oversized value by a marker, sparing its small children when that suffices.

    A step that nests several facts under one key (``parsed.<output_key>.<fact>``) would lose
    all of them for the sake of one big list: the oversized children are replaced one by one
    first, and the whole value only when it is still too large afterwards.
    """
    value = container[key]
    if isinstance(value, dict):
        for child_key, child in value.items():
            child_size = _size(child)
            if child_size > value_max:
                value[child_key] = _marker(child_size)
        if _size(value) <= value_max:
            return
    container[key] = _marker(size)


def _slots(context: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Every ``(container, key)`` whose value may be replaced by a marker."""
    slots: list[tuple[dict[str, Any], str]] = []

    def add_mapping(mapping: Any) -> None:
        if isinstance(mapping, dict):
            slots.extend((mapping, key) for key in mapping)

    add_mapping(context.get("metadata"))
    devices = context.get("devices")
    for device in devices.values() if isinstance(devices, dict) else ():
        if not isinstance(device, dict):
            continue
        add_mapping(device.get("parsed"))
        bags = device.get("attribute_bags")
        for bag in bags.values() if isinstance(bags, dict) else ():
            add_mapping(bag)
    return slots


def cap_persisted_output(
    persisted: dict[str, dict[str, Any]], *, value_max: int, total_max: int
) -> dict[str, dict[str, Any]]:
    """Return ``persisted`` (``{outcome name: context dump}``) with oversized values replaced."""
    sized: list[tuple[int, dict[str, Any], str]] = []
    for context in persisted.values():
        if not isinstance(context, dict):
            continue
        for container, key in _slots(context):
            value = container[key]
            if isinstance(value, dict) and value.get(TRUNCATED_KEY):
                continue
            sized.append((_size(value), container, key))

    for size, container, key in sized:
        if size > value_max:
            _shrink(container, key, size, value_max)

    remaining = sorted(
        (
            (_size(container[key]), container, key)
            for _, container, key in sized
            if not _is_marker(container[key])
        ),
        key=lambda item: item[0],
    )
    total = _size(persisted)
    while total > total_max and remaining:
        size, container, key = remaining.pop()  # largest first
        container[key] = _marker(size)
        total = _size(persisted)
    return persisted
