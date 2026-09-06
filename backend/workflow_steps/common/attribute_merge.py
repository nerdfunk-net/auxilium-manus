"""Deep-merge a parsed mapping into a device attribute-bag subtree.

Used by the ``read-from-file`` step. Distinct from ``attribute_write.py``
(single-leaf assignment, sealed-secret value model) and from
``attribute_defaults.merge_nautobot_defaults`` (which special-cases the
``interfaces`` / ``custom_fields`` keys and treats empty strings as "missing").
This helper is a plain recursive dict merge with an explicit overwrite flag.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from models.workflow_context import Capability, DeviceContext
from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS
from workflow_steps.common.attribute_write import RESERVED_BAG_NAMES


def deep_merge_mapping(
    base: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    overwrite: bool,
) -> dict[str, Any]:
    """Recursively merge *incoming* into *base*, returning a new ``dict``.

    Neither argument is mutated (nested dicts are copied along the merge path).

    * key only in *incoming* → added
    * key only in *base* → kept
    * both values are mappings → recurse
    * leaf collision (scalar / list / dict-vs-scalar type mismatch):
        - ``overwrite=True`` → the *incoming* value wins
        - ``overwrite=False`` → the *base* value is kept untouched
    * lists are replaced wholesale (subject to ``overwrite``), never
      concatenated or unioned
    """
    merged: dict[str, Any] = dict(base)
    for key, incoming_value in incoming.items():
        current = merged.get(key)
        if key in merged and isinstance(current, Mapping) and isinstance(incoming_value, Mapping):
            merged[key] = deep_merge_mapping(current, incoming_value, overwrite=overwrite)
        elif key not in merged or overwrite:
            merged[key] = incoming_value
    return merged


def validate_merge_destination(attribute_path: str) -> tuple[str, str]:
    """Split ``bag`` or ``bag.field.sub`` into ``(bag_name, remainder)``.

    Unlike :func:`attribute_write.set_device_attribute`, a bare bag name (no
    dot) is allowed — it means "merge at the root of that bag".

    Raises ``ValueError`` for an empty path, a ``device.``-prefixed path, a
    first segment that is a device scalar field, or a first segment in
    :data:`RESERVED_BAG_NAMES` (``parsed`` / ``run_input``).
    """
    path = (attribute_path or "").strip()
    if not path:
        raise ValueError("destination path is required")
    if path.startswith("device."):
        raise ValueError("destination path cannot target device.* fields")

    bag_name, _, remainder = path.partition(".")
    if bag_name in DEVICE_SCALAR_FIELDS:
        raise ValueError(f"destination path cannot target the device scalar field {bag_name!r}")
    if bag_name in RESERVED_BAG_NAMES:
        raise ValueError(
            f"{bag_name!r} is a reserved namespace (populated by the workflow engine) "
            "and cannot be written to"
        )
    return bag_name, remainder


def merge_into_device_attribute(
    device: DeviceContext,
    attribute_path: str,
    mapping: Mapping[str, Any],
    *,
    overwrite: bool,
) -> DeviceContext:
    """Deep-merge *mapping* into a freshly-copied attribute-bag subtree at
    *attribute_path* and return a new :class:`DeviceContext`.

    Copies every bag so the returned device shares no mutable state with the
    input; ORs :data:`Capability.ATTRIBUTES` onto the device. Never touches
    ``DeviceContext.parsed`` / the ``run_input`` bag.
    """
    bag_name, remainder = validate_merge_destination(attribute_path)

    attribute_bags = {name: dict(bag) for name, bag in device.attribute_bags.items()}
    target_bag = dict(attribute_bags.get(bag_name, {}))

    if remainder:
        parts = remainder.split(".")
        # Walk/copy to the parent of the final segment, creating dicts as needed.
        cursor: dict[str, Any] = target_bag
        for part in parts[:-1]:
            nxt = cursor.get(part)
            nxt = dict(nxt) if isinstance(nxt, Mapping) else {}
            cursor[part] = nxt
            cursor = nxt
        leaf = parts[-1]
        existing = cursor.get(leaf)
        if isinstance(existing, Mapping):
            cursor[leaf] = deep_merge_mapping(existing, mapping, overwrite=overwrite)
        elif existing is None or existing == "" or existing == [] or overwrite:
            # Absent / empty destination, or overwrite requested → drop the parsed
            # mapping in. A non-empty scalar/list already there is kept unless
            # overwrite is on.
            cursor[leaf] = dict(mapping)
    else:
        target_bag = deep_merge_mapping(target_bag, mapping, overwrite=overwrite)

    attribute_bags[bag_name] = target_bag
    return device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )
