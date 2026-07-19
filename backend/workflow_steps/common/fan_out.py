"""Helpers for building the ``_fan_out`` context metadata inventory steps emit."""

from __future__ import annotations

from typing import Any


def build_fan_out_metadata(
    fan_out_cfg: dict[str, Any] | None, node_id: str
) -> dict[str, Any] | None:
    """Sanitise a step's ``fan_out`` pluginConfig into ``_fan_out`` context metadata.

    Returns ``None`` when fan-out is disabled or the config is absent/malformed.
    """
    cfg = fan_out_cfg or {}
    if not bool(cfg.get("enabled", False)):
        return None

    raw_approval = cfg.get("approval")
    approval_cfg: dict[str, Any] = raw_approval if isinstance(raw_approval, dict) else {}

    return {
        "enabled": True,
        "mode": cfg.get("mode", "per_device"),
        "chunk_size": max(1, int(cfg.get("chunk_size", 1))),
        "max_concurrency": max(0, int(cfg.get("max_concurrency", 0))),
        "inventory_node_id": node_id,
        "approval": {
            "enabled": bool(approval_cfg.get("enabled", False)),
            "batch_size": max(1, int(approval_cfg.get("batch_size", 1))),
            "first_batch_auto": bool(approval_cfg.get("first_batch_auto", True)),
        },
    }
