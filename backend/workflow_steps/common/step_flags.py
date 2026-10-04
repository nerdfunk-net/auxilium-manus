"""Shared helpers for step config flags and dry-run previews."""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext, DeviceStatus

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def parse_bool_flag(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    """A boolean config value that may arrive as a bool, a string like ``"true"``, or a number."""
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def record_dry_run(
    device: DeviceContext, *, node_id: str, payload: dict[str, Any]
) -> DeviceContext:
    """Record what a step would have done, keyed by node_id so multiple dry-run steps in the
    same workflow don't clobber each other's preview.

    This is execution-preview metadata, not a workflow-consumable attribute -- it belongs on
    ``dry_run_results``, not ``attribute_bags`` (which downstream Jinja templates and Update
    Attribute/Log Attributes steps read and write).
    """
    results = dict(device.dry_run_results)
    results[node_id] = payload
    return device.model_copy(update={"status": DeviceStatus.OK, "dry_run_results": results})
