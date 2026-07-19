"""Resolve dot-path attribute values from a DeviceContext."""

from __future__ import annotations

from enum import Enum
from typing import Any

from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    is_sealed_secret,
    unwrap_secret,
)

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


class AttributeState(str, Enum):
    """Existence/emptiness classification for an attribute path resolution.

    Distinguishes "the key isn't there at all" (ABSENT) from "the key is
    there but holds null" (NULL) from "the key holds an empty string/list/
    dict" (EMPTY) from "the key holds real content" (PRESENT) — needed so
    steps like route-on-attribute can route on `{absent}` / `{null}` /
    `{empty}` / `{exists}` instead of only matching literal string values.
    """

    ABSENT = "absent"
    NULL = "null"
    EMPTY = "empty"
    PRESENT = "present"


_MISSING = object()


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


def _traverse_path_raw(root: Any, path: str) -> Any:
    """Like ``_traverse_path`` but returns ``_MISSING`` when a key along the
    path doesn't exist, instead of collapsing that case into ``None``."""
    current = root
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _classify_value(value: Any) -> tuple[AttributeState, str | None]:
    if value is None:
        return AttributeState.NULL, None
    if isinstance(value, (dict, list)):
        return (AttributeState.PRESENT, None) if len(value) > 0 else (AttributeState.EMPTY, None)
    text = str(value).strip()
    if not text:
        return AttributeState.EMPTY, None
    return AttributeState.PRESENT, text


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


def _resolve_leaf(value: Any, *, reveal_secrets: bool) -> str | None:
    """Stringify a resolved bag leaf, unwrapping (or redacting) a sealed secret."""
    if is_sealed_secret(value):
        if not reveal_secrets:
            return REDACTED_PLACEHOLDER
        return unwrap_secret(value)
    return _stringify(value)


def resolve_device_attribute(
    device: DeviceContext, attribute_path: str, *, reveal_secrets: bool = True
) -> str | None:
    """Resolve a dot path against device scalars and namespaced attribute bags.

    ``reveal_secrets`` controls what happens when the resolved leaf is a
    sealed secret envelope (see ``services.workflow_context.secret_fields``):
    ``True`` (the default — for trusted consumers like Jinja rendering and
    ISE-update expressions) decrypts it in-memory for this call; ``False``
    (for generic/bulk callers such as ``update-attribute`` and
    ``workflow-log``, which must never rehydrate or re-expose a secret)
    returns ``REDACTED_PLACEHOLDER`` instead.
    """
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
        raw = _traverse_path(bag, remainder)
        return _resolve_leaf(raw, reveal_secrets=reveal_secrets)

    bag = device.attribute_bags.get(path)
    if bag is None:
        return None
    if isinstance(bag, dict) and len(bag) == 1:
        only_value = next(iter(bag.values()))
        return _resolve_leaf(only_value, reveal_secrets=reveal_secrets)
    return None


def resolve_device_attribute_state(
    device: DeviceContext, attribute_path: str
) -> tuple[AttributeState, str | None]:
    """Resolve a dot path and classify it as absent/null/empty/present.

    Unlike ``resolve_device_attribute``, this distinguishes a path whose key
    doesn't exist at all (``ABSENT``) from one whose value is explicitly
    ``None`` (``NULL``) from one whose value is an empty string/list/dict
    (``EMPTY``) — needed for steps that route on those states rather than on
    a literal string value (for example: "was a TACACS+ key ever set?").
    """
    path = attribute_path.strip()
    if not path:
        return AttributeState.ABSENT, None

    if path.startswith("device."):
        field_name = path[len("device.") :].split(".", 1)[0]
        if field_name not in _DEVICE_SCALAR_FIELDS or "." in path[len("device.") :]:
            return AttributeState.ABSENT, None
        return _classify_value(getattr(device, field_name))

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return _classify_value(getattr(device, path))

    if "." in path:
        bag_name, remainder = path.split(".", 1)
        bag = device.attribute_bags.get(bag_name)
        if bag is None:
            return AttributeState.ABSENT, None
        raw = _traverse_path_raw(bag, remainder)
        if raw is _MISSING:
            return AttributeState.ABSENT, None
        return _classify_value(raw)

    bag = device.attribute_bags.get(path)
    if bag is None:
        return AttributeState.ABSENT, None
    if isinstance(bag, dict):
        if len(bag) == 0:
            return AttributeState.EMPTY, None
        if len(bag) == 1:
            return _classify_value(next(iter(bag.values())))
        return AttributeState.PRESENT, None
    return _classify_value(bag)
