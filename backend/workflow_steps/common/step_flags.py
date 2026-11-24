"""Shared helpers for step config flags and dry-run previews."""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext, DeviceStatus
from services.workflow_context.flags import parse_bool_flag, parse_int_flag

__all__ = ["parse_bool_flag", "parse_int_flag", "record_dry_run", "require_text"]


def require_text(
    config: dict[str, Any], key: str, *, step_id: str, default: str | None = None
) -> str:
    """The stripped text of ``config[key]``, or of ``default`` when the key is unset or empty.

    Blank after stripping is a configuration error naming the step and the key.
    """
    value = str(config.get(key) or default or "").strip()
    if not value:
        raise ValueError(f"{step_id}: {key} is required")
    return value


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
