"""Executor for the batfish-interface-properties step.

Wraps Batfish's `interfaceProperties` question against the snapshot an
upstream batfish-init-snapshot step initialized (resolved via
workflow_steps.common.batfish_context). Pure read -- does not touch
context.devices as input; the result is stored as one workflow-level
artifact plus a row-count summary in WorkflowContext.metadata, same
convention batfish-node-properties/batfish-routing-table use.

**Not the same question as batfish-node-properties.** `nodeProperties`
returns one row per node (`Node` column, a plain string); `interfaceProperties`
returns one row per (node, interface) pair, keyed by an `Interface` column
that -- confirmed empirically, see doc/BATFISH_INTEGRATION.md "Batfish
Interface Properties" -- serializes to a nested `{"hostname": ...,
"interface": ...}` dict, not a plain string. This step's `devices` outcome
therefore dedupes via `devices_from_interface_rows`, not `devices_from_nodes`.

`route_empty_to_devices`/`empty_match_mode` mirror batfish-node-properties'
own audit feature exactly (same `_is_empty_value` semantics, same "any"/"all"
combination across multiple `properties`) -- see that step's module
docstring for the full reasoning. Here it answers per-interface questions
like "which interfaces have no description set" or "which interfaces have no
IP address configured", still surfaced through the same node-level `devices`
outcome (an interface finding with no matching node-level device is not
representable in this codebase's device model, so a device is flagged if
*any* of its matching interfaces meets the empty condition).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_interface_properties
from workflow_steps.batfish_interface_properties.config import get_config
from workflow_steps.common.batfish_context import (
    devices_from_interface_rows,
    resolve_batfish_snapshot_ref,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-interface-properties"
_EMPTY_MATCH_MODES = frozenset({"any", "all"})


def _is_empty_value(value: Any) -> bool:
    """A property value counts as empty if it's unset, blank, or an empty
    collection -- e.g. an interface with no description set."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _parse_properties_list(properties: str) -> list[str]:
    return [item.strip() for item in properties.split(",") if item.strip()]


def _row_matches_empty(
    row: dict[str, Any], *, properties_list: list[str], match_mode: str
) -> bool:
    empty_flags = [_is_empty_value(row.get(prop)) for prop in properties_list]
    if match_mode == "all":
        return all(empty_flags)
    return any(empty_flags)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: Batfish is reached via pybatfish, not Netmiko

    merged_config = {**get_config(), **config}
    properties_list = _parse_properties_list(str(merged_config.get("properties") or ""))
    route_empty_to_devices = bool(merged_config.get("route_empty_to_devices"))
    match_mode = str(merged_config.get("empty_match_mode") or "any").strip().lower()
    if route_empty_to_devices and not properties_list:
        raise ValueError(
            f"{_STEP_ID}: 'properties' is required when route_empty_to_devices is enabled -- "
            "Batfish's default (unfiltered) column set has no single well-defined notion of "
            "'empty' to check against."
        )
    if match_mode not in _EMPTY_MATCH_MODES:
        raise ValueError(
            f"{_STEP_ID}: empty_match_mode must be one of {sorted(_EMPTY_MATCH_MODES)}"
        )

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        snap.network,
        snap.snapshot,
    )

    rows = await query_interface_properties(
        batfish,
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=merged_config.get("nodes"),
        interfaces=merged_config.get("interfaces"),
        properties=merged_config.get("properties"),
    )

    output_key = str(
        merged_config.get("output_key") or "batfish_interface_properties"
    ).strip() or "batfish_interface_properties"

    content = json.dumps(rows, indent=2, default=str)
    artifact_ref = await artifact_service.store(
        content=content,
        kind="batfish_result",
        device_id=f"batfish-{node_id}",
        run_id=context.run_id,
        media_type="application/json",
    )

    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = {
        "kind": "batfish_result",
        "question": "interfaceProperties",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(rows),
    }

    if route_empty_to_devices:
        devices_rows = [
            row
            for row in rows
            if _row_matches_empty(row, properties_list=properties_list, match_mode=match_mode)
        ]
    else:
        devices_rows = rows
    device_nodes = devices_from_interface_rows(devices_rows)

    logger.info(
        "%s finished run_id=%s rows=%d devices=%d route_empty_to_devices=%s",
        _STEP_ID,
        run.id,
        len(rows),
        len(device_nodes),
        route_empty_to_devices,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{len(rows)} interface(s)",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]
