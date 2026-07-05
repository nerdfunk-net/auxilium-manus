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

DEVICE_SCALAR_FIELDS = _DEVICE_SCALAR_FIELDS

DEBUG_LOGS_METADATA_SUFFIX = ".debug_logs"


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


def build_device_value_context(
    device: DeviceContext,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a namespaced lookup tree for attribute path resolution."""
    from workflow_steps.common.device_template import build_template_context

    context = build_template_context(device, run_id=run_id)
    for bag_name, bag_value in device.attribute_bags.items():
        if bag_name not in context:
            context[bag_name] = dict(bag_value)
    context["capabilities"] = sorted(cap.value for cap in device.capabilities)
    context["status"] = device.status.value
    return context


def resolve_device_value(
    device: DeviceContext,
    attribute_path: str,
    *,
    run_id: str | None = None,
) -> Any:
    """Resolve a dot path and return the raw value (including dict/list)."""
    path = attribute_path.strip()
    if not path:
        return None

    context = build_device_value_context(device, run_id=run_id)

    if path.startswith("device."):
        field_name = path[len("device.") :]
        if "." not in field_name and field_name in _DEVICE_SCALAR_FIELDS:
            return getattr(device, field_name)
        return _traverse_path(context, path)

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return getattr(device, path)

    if "." in path:
        return _traverse_path(context, path)

    if path in context:
        return context[path]

    bag = device.attribute_bags.get(path)
    if bag is not None:
        return dict(bag)
    return None


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
