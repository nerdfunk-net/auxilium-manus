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

Everything past "fetch this question's rows" (artifact/metadata storage,
the route_empty_to_devices/empty_match_mode audit filter, and per-device
enrichment on the `devices` outcome) is shared with batfish-interface-
properties via `workflow_steps.common.batfish_properties` -- see that
module's docstring for the full reasoning and the extension point for a
future property-family question.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.node_properties_spec import NODE_PROPERTIES_SPEC
from services.batfish.query_helpers import query_node_properties
from workflow_steps.batfish_node_properties.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_properties import (
    build_property_outcomes,
    parse_properties_list,
    validate_empty_config,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-node-properties"

_SPEC = NODE_PROPERTIES_SPEC


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
