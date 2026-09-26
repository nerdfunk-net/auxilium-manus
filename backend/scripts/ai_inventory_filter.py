#!/usr/bin/env python3
"""Author-time helpers for a `get-nautobot-devices` node: converting a saved
inventory's `conditions` (version-2 tree format) into the canvas
`device_filter` shape `"fixed"` mode needs, and counting an inventory's live
device total (`count_inventory_devices`) to decide whether to propose
`fan_out`. The filter conversion is a faithful Python port of the relevant
slice of
`frontend/src/components/features/inventory/utils/tree-format-converters.ts`
(`conditionTreeToFilterTree` + its `convertConditionItems`/`convertConditionGroup`
helpers) plus `saved-conditions.ts`'s `savedConditionsToFilterTree` entry point.

Why this exists: see doc/ai_collaboration/AI_VOCABULARY.md's inventory-targeting
recipe. "fixed" mode is the default for a workflow meant to run live against a
named inventory (device_filter is a canvas-time snapshot); "run_param" mode
(scripts/ai_defaults.py has no part in that — see WorkflowValidationService's
reference checks instead) remains the right choice when the workflow will be
scheduled or needs a per-run/per-schedule inventory override.

Deliberately narrow: only the saved-conditions -> filter-tree direction is
ported (the direction actually needed here), and only for the version-2 tree
shape every real saved inventory is stored in (`isFilterTree`'s legacy-shape
fallback in the TS source is defensive frontend code for a shape that
`Inventory.conditions` is never actually written in — see
`services/sources/nautobot/persistence_service.py`'s `_model_to_dict`, which
always JSON-decodes to this exact `{"version": 2, "tree": {...}}` structure).
Malformed/empty input returns an empty tree, matching the frontend's own
`emptyTree()` fallback, rather than raising — this mirrors how the frontend
itself degrades (an inventory with no conditions selects nothing, not an
error), not a "guess" in the AI_DEFAULTS.md sense.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Above this many devices, propose enabling fan_out rather than defaulting to
# a single-workflow-run loop over every device — see
# doc/ai_collaboration/AI_VOCABULARY.md's "fan-out threshold" rule and
# AI_DEFAULTS.md's fan_out.max_concurrency policy default.
FAN_OUT_DEVICE_THRESHOLD = 10

# Proposed fan_out block when the threshold is crossed — mirrors
# get_nautobot_devices/config.py's own default shape with enabled/
# max_concurrency raised, never a config field this repo hasn't already
# defined.
DEFAULT_FAN_OUT_CONFIG = {
    "enabled": True,
    "mode": "per_device",
    "chunk_size": 1,
    "max_concurrency": 10,
}


async def _count_inventory_devices_async(
    db: Session, *, inventory_id: int, username: str, nautobot_source_id: str
) -> int:
    import service_factory
    from services.nautobot.client import NautobotService
    from workflow_steps.common.nautobot_source import resolve_nautobot_credentials

    credentials = resolve_nautobot_credentials(
        db, nautobot_source_id, step_id="ai_inventory_filter"
    )
    # get_nautobot_app_service() reads a module-global singleton normally
    # initialized once in main.py's app lifespan (NautobotService() +
    # startup(), which just opens two httpx.AsyncClient instances) — a
    # standalone script never runs through that lifespan, so it has to do
    # the same setup itself, and clean up after, same as the app would on
    # shutdown.
    nautobot_service = NautobotService()
    await nautobot_service.startup()
    try:
        service_factory.set_nautobot_app_service(nautobot_service)
        source_service = service_factory.build_nautobot_source_service(credentials, db)
        analysis = await source_service.analyze_inventory(inventory_id, username)
        return int(analysis.get("device_count", 0))
    finally:
        await nautobot_service.shutdown()


def count_inventory_devices(
    db: Session, *, inventory_id: int, username: str, nautobot_source_id: str
) -> int:
    """Live device count for a saved inventory, via the same code path
    get-nautobot-devices' own executor uses to actually resolve devices
    (resolve_nautobot_credentials + NautobotSourceService.analyze_inventory) —
    a filter-type inventory's true device count can only be known by
    evaluating its filter against the real Nautobot API, not by inspecting
    the DB alone. Raises ValueError (propagated from resolve_nautobot_credentials)
    if nautobot_source_id doesn't resolve — fail loudly, don't guess a count."""
    return asyncio.run(
        _count_inventory_devices_async(
            db,
            inventory_id=inventory_id,
            username=username,
            nautobot_source_id=nautobot_source_id,
        )
    )


def _empty_tree() -> dict[str, Any]:
    return {"id": "root", "logic": "AND", "negate": False, "items": []}


def _is_group(item: dict[str, Any]) -> bool:
    return item.get("type") == "group"


def _convert_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for item in items:
        if _is_group(item):
            converted.append(_convert_group(item))
        else:
            converted.append(
                {
                    "id": item.get("id"),
                    "field": item.get("field"),
                    "operator": item.get("operator"),
                    "value": item.get("value"),
                }
            )
    return converted


def _convert_group(group: dict[str, Any]) -> dict[str, Any]:
    # Saved "ConditionGroup" shape: `logic` is "AND"/"NOT" (is this group
    # itself negated?), `internalLogic` is the real AND/OR combinator for its
    # children. Canvas "FilterGroup" shape inverts that split: `logic` is the
    # AND/OR combinator, `negate` is the NOT flag. Exactly mirrors
    # tree-format-converters.ts::convertConditionGroup.
    return {
        "id": group.get("id"),
        "logic": group.get("internalLogic", "AND"),
        "negate": group.get("logic") == "NOT",
        "items": _convert_items(group.get("items", [])),
    }


def condition_tree_to_filter_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """Port of tree-format-converters.ts::conditionTreeToFilterTree. `tree`
    is a saved "ConditionTree": `{"type": "root", "internalLogic": ..., "items": [...]}`."""
    items = tree.get("items", [])
    root_group = {
        "id": "root",
        "logic": tree.get("internalLogic", "AND"),
        "negate": False,
        "items": _convert_items(items),
    }
    # Special case: a single top-level NOT-wrapped group unwraps to
    # `negate: true` at the root instead of a nested group — matches the
    # frontend exactly, including that this ONLY applies when the NOT group
    # is the tree's one and only item.
    if len(items) == 1 and _is_group(items[0]) and items[0].get("logic") == "NOT":
        not_group = items[0]
        return {
            "id": "root",
            "logic": not_group.get("internalLogic", "AND"),
            "negate": True,
            "items": _convert_items(not_group.get("items", [])),
        }
    return root_group


def saved_conditions_to_device_filter(conditions: Any) -> dict[str, Any]:
    """Port of saved-conditions.ts::savedConditionsToFilterTree. `conditions`
    is an `Inventory.conditions` value, e.g. from
    `InventoryService.get_inventory_by_name(...)["conditions"]` — already
    JSON-decoded to `[{"version": 2, "tree": {...}}]`, never a raw string."""
    if not isinstance(conditions, list) or not conditions:
        return _empty_tree()
    first = conditions[0]
    if not isinstance(first, dict) or first.get("version") != 2:
        return _empty_tree()
    tree = first.get("tree")
    if not isinstance(tree, dict) or tree.get("type") != "root":
        return _empty_tree()
    return condition_tree_to_filter_tree(tree)
