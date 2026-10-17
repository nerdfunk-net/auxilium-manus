"""Detect two devices that map to one storage key (DN-F)."""

from __future__ import annotations

from collections.abc import Iterable

from models.failure import FailureInfo

DUPLICATE_KEY_CODE = "duplicate_key"
DUPLICATE_KEY_FAILURE = FailureInfo(phase="internal", kind="ambiguous_match")


def find_duplicate_keys(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    """``(device_id, key)`` pairs -> ``{device_id: first_device_id_with_that_key}`` for every
    later duplicate. The first device owning a key is never reported."""
    first: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    for device_id, key in items:
        owner = first.setdefault(key, device_id)
        if owner != device_id:
            duplicates[device_id] = owner
    return duplicates
