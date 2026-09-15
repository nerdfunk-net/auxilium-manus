"""Executor for the batfish-node-properties step.

Wraps Batfish's `nodeProperties` question against the snapshot an upstream
batfish-init-snapshot step initialized (resolved via
workflow_steps.common.batfish_context). Pure read -- does not touch
context.devices as input; the result is stored as one workflow-level
artifact plus a row-count summary in WorkflowContext.metadata, same
convention batfish-routing-table uses (see doc/BATFISH_INTEGRATION.md
"Batfish Routing Table" -> "Result storage").

Unlike batfish-start-run's own internal use of this same question (always
unfiltered, since it only needs node identity for dedup), this step exposes
the `properties` NodePropertySpec filter directly -- letting a workflow ask,
e.g., "does R1 have a TACACS server configured" without needing an upstream
Render Jinja Template step or per-device expected values the way
batfish-validate-facts's `field` mode does.

**`success` vs. `devices`: different enrichment, by design.** `success`
passes `context` straight through unchanged (plus the shared metadata/
artifact) -- exactly like batfish-routing-table's own `success` outcome. But
`devices` is meant to be consumed per-device downstream (Log Attributes,
Render Jinja Template, a device-detail dialog), so each device there is
enriched with its own row's fields at `device.parsed[f"{node_id}.
{output_key}"]` (same `{"parsed": ..., "error": None}` shape
batfish-extract-facts/batfish-validate-facts use) -- built by `_enrich_devices`,
layered on top of the shared `devices_from_nodes` helper via
`device.model_copy`, the same idiom those two steps already use. Before this,
`devices` carried identity only, and the *only* place the actual property
values lived was the one shared, un-partitioned artifact covering every
queried node -- which a per-device UI/step showed identically regardless of
which device you were looking at (see doc/BATFISH_INTEGRATION.md "Batfish
Node Properties" -> "devices outcome: per-device enrichment").

**`route_empty_to_devices` (default off).** Batfish always returns one row
per matched node, even when the requested property is unset -- an
unconfigured TACACS server shows up as `{"Node": "lab-2", "TACACS_Servers":
[]}`, not a missing row. Left disabled, the `devices` outcome carries every
matched node, same as today. Enabled, it's filtered down to only the nodes
whose requested `properties` are empty (see `_is_empty_value` for what
counts as empty: `None`, a blank/whitespace-only string, or an empty
list/dict/tuple/set) -- turning this step into an audit ("which devices are
missing a TACACS server") rather than a plain lookup. Requires `properties`
to be set explicitly (raises `ValueError` otherwise) -- with no properties
filter, Batfish returns dozens of unrelated default columns and "empty" has
no single well-defined meaning across all of them.

**`empty_match_mode` ("any" | "all"), only load-bearing with >1 property.**
With multiple `properties` configured, a node can have some empty and some
not -- `"any"` (default) flags it if at least one requested property is
empty (the stricter read: every requested property must be present), `"all"`
flags it only if every requested property is empty.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_node_properties
from workflow_steps.batfish_node_properties.config import get_config
from workflow_steps.common.batfish_context import devices_from_nodes, resolve_batfish_snapshot_ref

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-node-properties"
_EMPTY_MATCH_MODES = frozenset({"any", "all"})


def _is_empty_value(value: Any) -> bool:
    """A property value counts as empty if it's unset, blank, or an empty
    collection -- e.g. Batfish's own `TACACS_Servers: []` for a node with no
    TACACS server configured."""
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


def _enrich_devices(
    rows: list[dict[str, Any]], *, node_id: str, output_key: str
) -> dict[str, DeviceContext]:
    """Build the `devices` outcome's devices, each carrying its own row's
    fields -- unlike `devices_from_nodes` alone (identity only), used
    as-is by batfish-start-run/batfish-routing-table, which have no
    per-device data to attach."""
    parsed_key = f"{node_id}.{output_key}"
    fields_by_node = {
        row["Node"]: {key: value for key, value in row.items() if key != "Node"}
        for row in rows
        if row.get("Node")
    }
    enriched: dict[str, DeviceContext] = {}
    for node, device in devices_from_nodes(rows).items():
        parsed = dict(device.parsed)
        parsed[parsed_key] = {"parsed": fields_by_node.get(node, {}), "error": None}
        enriched[node] = device.model_copy(
            update={"parsed": parsed, "capabilities": device.capabilities | {Capability.PARSED}}
        )
    return enriched


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

    rows = await query_node_properties(
        batfish,
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=merged_config.get("nodes"),
        properties=merged_config.get("properties"),
    )

    output_key = str(
        merged_config.get("output_key") or "batfish_node_properties"
    ).strip() or "batfish_node_properties"

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
        "question": "nodeProperties",
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
    device_nodes = _enrich_devices(devices_rows, node_id=node_id, output_key=output_key)

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
            summary=f"{len(rows)} node(s)",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]
