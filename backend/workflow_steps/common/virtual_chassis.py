"""Shared shape of a virtual-chassis (switch stack) device's attribute bag.

``get-virtual-chassis`` writes the bag, ``split-virtual-chassis`` reads it back and rebuilds
per-member bags. Both go through ``member_bag`` so a split member looks the same whether it
was split at inventory time or after a command ran against the whole stack.
"""

from __future__ import annotations

from typing import Any

from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS
from workflow_steps.common.attribute_write import RESERVED_BAG_NAMES

DEFAULT_BAG_NAME = "virtual_chassis"
DEFAULT_INDEX_KEY = "stack_index"

# Fields of a member record that identify the *device* (they become DeviceContext fields)
# rather than describe it inside the bag.
_DEVICE_LEVEL_RECORD_FIELDS = frozenset({"id", "name", "primary_ip4"})


def plain_name(config: dict[str, Any], key: str, default: str, *, step_id: str) -> str:
    """A non-empty config name without dots (it is used as one attribute path segment)."""
    value = str(config.get(key) or default).strip()
    if not value or "." in value:
        raise ValueError(f"{step_id}: {key} must be a non-empty name without dots")
    return value


def bag_name(config: dict[str, Any], *, step_id: str) -> str:
    """The configured ``attribute_bag``, rejecting reserved and device-field names."""
    name = plain_name(config, "attribute_bag", DEFAULT_BAG_NAME, step_id=step_id)
    if name in RESERVED_BAG_NAMES or name in DEVICE_SCALAR_FIELDS:
        raise ValueError(f"{step_id}: attribute_bag {name!r} is a reserved name")
    return name


def member_bag(
    *,
    vc_id: str,
    vc_name: str,
    member_count: int,
    record: dict[str, Any],
    master_name: str,
) -> dict[str, Any]:
    """Attribute bag of one stack member: stack-wide fields plus the member's own record."""
    own = {k: v for k, v in record.items() if k not in _DEVICE_LEVEL_RECORD_FIELDS}
    return {
        "vc_id": vc_id,
        "vc_name": vc_name,
        "member_count": member_count,
        **own,
        "master_name": master_name,
    }
