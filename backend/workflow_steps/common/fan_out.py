"""Helpers for building the ``_fan_out`` context metadata inventory steps emit."""

from __future__ import annotations

from typing import Any, NamedTuple

from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag


def _int(cfg: dict[str, Any], key: str, default: int) -> int:
    """A whole number; out-of-range values are clamped by the caller (a blank means ``default``)."""
    return parse_int_flag(cfg, key, default=default, minimum=-(2**31))


def build_fan_out_metadata(
    fan_out_cfg: dict[str, Any] | None, node_id: str
) -> dict[str, Any] | None:
    """Sanitise a step's ``fan_out`` pluginConfig into ``_fan_out`` context metadata.

    Returns ``None`` when fan-out is disabled or the config is absent/malformed.
    """
    cfg = fan_out_cfg or {}
    if not parse_bool_flag(cfg, "enabled", default=False):
        return None

    raw_approval = cfg.get("approval")
    approval_cfg: dict[str, Any] = raw_approval if isinstance(raw_approval, dict) else {}

    return {
        "enabled": True,
        "mode": cfg.get("mode", "per_device"),
        "chunk_size": max(1, _int(cfg, "chunk_size", 1)),
        "max_concurrency": max(0, _int(cfg, "max_concurrency", 0)),
        "inventory_node_id": node_id,
        "approval": {
            "enabled": parse_bool_flag(approval_cfg, "enabled", default=False),
            "batch_size": max(1, _int(approval_cfg, "batch_size", 1)),
            "first_batch_auto": parse_bool_flag(approval_cfg, "first_batch_auto", default=True),
        },
    }


class InventoryMetadata(NamedTuple):
    """Context metadata of an inventory step.

    ``success`` carries the ``_fan_out`` marker (the runner reads it from the success outcome
    only); ``base`` is the same without it, for a failure branch that carries stub devices.
    """

    base: dict[str, Any]
    success: dict[str, Any]


def inventory_metadata(
    context_metadata: dict[str, Any],
    node_id: str,
    fan_out_cfg: dict[str, Any] | None,
    **entries: Any,
) -> InventoryMetadata:
    """The metadata an inventory step returns: the context's, ``{node_id}.<key>`` per entry, and
    ``_fan_out`` on the success side when the step's ``fan_out`` config enables it."""
    base = {**context_metadata, **{f"{node_id}.{key}": value for key, value in entries.items()}}
    fan_out = build_fan_out_metadata(fan_out_cfg, node_id)
    success = {**base} if fan_out is None else {**base, "_fan_out": fan_out}
    return InventoryMetadata(base=base, success=success)
