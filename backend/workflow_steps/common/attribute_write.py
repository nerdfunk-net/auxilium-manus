"""Write dot-path attribute values onto a DeviceContext."""

from __future__ import annotations

from typing import Any

from models.workflow_context import Capability, DeviceContext
from services.workflow_context.attribute_path import (
    DEVICE_SCALAR_FIELDS,
    FILTER_SEGMENT_RE,
    INDEX_SEGMENT_RE,
    split_path_segments,
)

_READ_ONLY_DEVICE_FIELDS = frozenset({"id", "source", "source_id"})

# "parsed" is a reserved read namespace backed by DeviceContext.parsed (see
# attribute_path.py) — populated only by step executors (parse-cisco-config,
# render-jinja-template, filter-output, ...), never by generic attribute
# writes. Writing "parsed.foo" here would land in attribute_bags["parsed"]
# instead, which the read side ignores entirely (it always reads
# DeviceContext.parsed for this name), making the write silently unreadable.
#
# "run_input" is reserved for the same reason as "parsed" is precious but for
# the opposite direction: StepRunner stamps it onto every device from
# WorkflowRun.run_inputs (see services/workflow_context/run_inputs.py) and a
# generic write here could silently overwrite what the operator supplied at
# trigger time for the rest of the run.
_RESERVED_BAG_NAMES = frozenset({"parsed", "run_input"})

# Public alias for reuse by other attribute writers (e.g. attribute_merge.py).
RESERVED_BAG_NAMES = _RESERVED_BAG_NAMES


def _write_into_list_item(
    current: dict[str, Any], segment_match: Any, rest: list[str], value: Any
) -> None:
    """Handle a ``key[field=value]`` segment: find (or append) the list item and write into it.

    The list and the matched item are copied before being written to, so the originals
    (which other devices and sibling branches may share) are never mutated.
    """
    key = segment_match.group("key")
    field = segment_match.group("field").strip()
    match_value = segment_match.group("value")
    if not match_value.strip() or any(c in field for c in "[]="):
        raise ValueError(f"selector {segment_match.group(0)!r} needs a field and a non-empty value")
    if "." in field:
        # The reader resolves a dotted field inside each item; the writer can only match, and
        # create, a flat key, so it would append an item the reader never finds.
        raise ValueError(
            f"selector {segment_match.group(0)!r}: a write needs a flat field, not the path "
            f"{field!r}"
        )
    if not rest:
        raise ValueError(
            f"selector {segment_match.group(0)!r} must be followed by the field to write "
            f"(for example {segment_match.group(0)}.mac_address)"
        )

    existing = current.get(key)
    if existing is None:
        items: list[Any] = []
    elif isinstance(existing, list):
        items = list(existing)
    else:
        raise ValueError(
            f"{key!r} is not a list, so {segment_match.group(0)!r} cannot select an item"
        )

    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get(field)) == match_value:
            target = dict(item)
            items[index] = target
            break
    else:
        target = {field: match_value}
        items.append(target)

    current[key] = items
    _write_segments(target, rest, value)


def _reject_index_segment(part: str) -> None:
    if INDEX_SEGMENT_RE.match(part):
        raise ValueError(
            f"path segment {part!r}: a write cannot target a list position; select the item by "
            "a field instead (for example interfaces[name=Gi0/0])"
        )


def _write_segments(current: dict[str, Any], parts: list[str], value: Any) -> None:
    for position, part in enumerate(parts[:-1] if parts else []):
        _reject_index_segment(part)
        selector = FILTER_SEGMENT_RE.match(part)
        if selector:
            _write_into_list_item(current, selector, parts[position + 1 :], value)
            return
        existing = current.get(part)
        next_value = dict(existing) if isinstance(existing, dict) else {}
        current[part] = next_value
        current = next_value
    last = parts[-1]
    _reject_index_segment(last)
    selector = FILTER_SEGMENT_RE.match(last)
    if selector:
        _write_into_list_item(current, selector, [], value)
        return
    current[last] = value


def _set_nested(root: dict[str, Any], path: str, value: Any) -> None:
    """Set *value* at *path* inside *root*, which must be a fresh (already copied) dict.

    Every dict on the way down is copied before it is written to, so the dicts of the
    original device - which other devices and sibling branches may share - are never
    mutated. A ``key[field=value]`` segment selects (or appends) an item of a list of dicts,
    e.g. ``interfaces[name=Gi0/0.100].mac_address``.
    """
    _write_segments(root, split_path_segments(path), value)


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
            f"{bag_name!r} is a reserved namespace (populated by the workflow engine, "
            "not by update-attribute) and cannot be written to"
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
