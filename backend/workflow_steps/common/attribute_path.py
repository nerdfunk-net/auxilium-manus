"""Resolve dot-path attribute values from a DeviceContext."""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext

_DEVICE_SCALAR_FIELDS = frozenset(
    {
        "id",
        "name",
        "hostname",
        "platform",
        "network_driver",
        "primary_ip4",
        "source",
        "source_id",
    }
)


def _traverse_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
            continue
        return None
    return current


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def resolve_device_attribute(device: DeviceContext, attribute_path: str) -> str | None:
    """Resolve a dot path against device scalars and namespaced attribute bags."""
    path = attribute_path.strip()
    if not path:
        return None

    if path.startswith("device."):
        field_name = path[len("device.") :].split(".", 1)[0]
        if field_name not in _DEVICE_SCALAR_FIELDS:
            return None
        if "." in path[len("device.") :]:
            return None
        return _stringify(getattr(device, field_name))

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return _stringify(getattr(device, path))

    if "." in path:
        bag_name, remainder = path.split(".", 1)
        bag = device.attribute_bags.get(bag_name)
        if bag is None:
            return None
        return _stringify(_traverse_path(bag, remainder))

    bag = device.attribute_bags.get(path)
    if bag is None:
        return None
    if isinstance(bag, dict) and len(bag) == 1:
        only_value = next(iter(bag.values()))
        return _stringify(only_value)
    return None
