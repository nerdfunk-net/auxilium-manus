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
therefore dedupes via `devices_from_interface_rows`, not `devices_from_nodes`,
and nests each device's own fields under `parsed[...]["parsed"]["Interfaces"]`
rather than flat -- the one real difference from batfish-node-properties,
captured as this step's own `PropertyQuestionSpec` passed into the shared
`workflow_steps.common.batfish_properties` engine (route_empty_to_devices/
empty_match_mode, artifact/metadata storage, and per-device enrichment are
otherwise identical between the two steps -- see that module's docstring).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_interface_properties
from workflow_steps.batfish_interface_properties.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_properties import (
    PropertyQuestionSpec,
    build_property_outcomes,
    parse_properties_list,
    validate_empty_config,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-interface-properties"


def _interface_node_key(row: dict[str, Any]) -> str | None:
    interface = row.get("Interface")
    return interface.get("hostname") if isinstance(interface, dict) else None


def _build_interfaces_parsed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every matching interface's own fields for one node, nested the same
    way `pybatfish.client._facts.get_facts()` nests this question's results."""
    interfaces: dict[str, dict[str, Any]] = {}
    for row in rows:
        interface = row.get("Interface")
        name = interface.get("interface") if isinstance(interface, dict) else None
        if not name:
            continue
        interfaces[str(name)] = {key: value for key, value in row.items() if key != "Interface"}
    return {"Interfaces": interfaces}


_SPEC = PropertyQuestionSpec(
    question_label="interfaceProperties",
    node_key=_interface_node_key,
    build_parsed_for_node=_build_interfaces_parsed,
    row_noun="interface(s)",
)


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
    properties_list = parse_properties_list(str(merged_config.get("properties") or ""))
    route_empty_to_devices = bool(merged_config.get("route_empty_to_devices"))
    match_mode = str(merged_config.get("empty_match_mode") or "any").strip().lower()
    validate_empty_config(
        step_id=_STEP_ID,
        route_empty_to_devices=route_empty_to_devices,
        properties_list=properties_list,
        match_mode=match_mode,
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

    return await build_property_outcomes(
        spec=_SPEC,
        rows=rows,
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        route_empty_to_devices=route_empty_to_devices,
        properties_list=properties_list,
        match_mode=match_mode,
    )
