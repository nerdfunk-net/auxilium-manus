"""Write dot-path attribute values onto a DeviceContext."""

from __future__ import annotations

from typing import Any

from models.workflow_context import Capability, DeviceContext
from workflow_steps.common.attribute_path import DEVICE_SCALAR_FIELDS

_READ_ONLY_DEVICE_FIELDS = frozenset({"id", "source", "source_id"})

# "parsed" is a reserved read namespace backed by DeviceContext.parsed (see
# attribute_path.py) — populated only by step executors (parse-cisco-config,
# render-jinja-template, filter-output, ...), never by generic attribute
# writes. Writing "parsed.foo" here would land in attribute_bags["parsed"]
# instead, which the read side ignores entirely (it always reads
# DeviceContext.parsed for this name), making the write silently unreadable.
_RESERVED_BAG_NAMES = frozenset({"parsed"})


def _set_nested(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = root
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def set_device_attribute(device: DeviceContext, attribute_path: str, value: Any) -> DeviceContext:
    """Set *value* at *attribute_path*, creating nested bags as needed.

    *value* is normally a string, but may be a sealed-secret envelope dict
    (see ``services.workflow_context.secret_fields.seal_secret``) for known
    secret paths.
    """
    path = attribute_path.strip()
    if not path:
        raise ValueError("attribute path is required")

    if path.startswith("device."):
        field_name = path[len("device.") :]
        if "." in field_name:
            raise ValueError(
                "device.* paths support only top-level scalar fields "
                "(for example device.name or device.platform)"
            )
        if field_name not in DEVICE_SCALAR_FIELDS:
            raise ValueError(f"unknown device field: {field_name}")
        if field_name in _READ_ONLY_DEVICE_FIELDS:
            raise ValueError(f"device field is read-only: {field_name}")
        return device.model_copy(
            update={
                field_name: value,
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            }
        )

    if "." not in path:
        if path in DEVICE_SCALAR_FIELDS:
            if path in _READ_ONLY_DEVICE_FIELDS:
                raise ValueError(f"device field is read-only: {path}")
            return device.model_copy(
                update={
                    path: value,
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                }
            )
        raise ValueError(
            "attribute path must use bag.field form (for example nautobot.location.name)"
        )

    bag_name, remainder = path.split(".", 1)
    if bag_name in DEVICE_SCALAR_FIELDS:
        raise ValueError("use device.* prefix for device scalar fields")
    if bag_name in _RESERVED_BAG_NAMES:
        raise ValueError(
            f"{bag_name!r} is a reserved namespace populated by workflow steps "
            "(e.g. parse-cisco-config, render-jinja-template) and cannot be "
            "written via update-attribute"
        )

    attribute_bags = {name: dict(bag) for name, bag in device.attribute_bags.items()}
    bag = dict(attribute_bags.get(bag_name, {}))
    _set_nested(bag, remainder, value)
    attribute_bags[bag_name] = bag

    return device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )
