"""Executor for the batfish-routing-table step.

Wraps Batfish's `routes` question against the snapshot an upstream
batfish-init-snapshot step initialized (resolved via
workflow_steps.common.batfish_context). Pure read -- does not touch
context.devices; the result is stored as one workflow-level artifact plus a
row-count summary in WorkflowContext.metadata (see doc/BATFISH_INTEGRATION.md
"Batfish Routing Table" -> "Result storage" for why this isn't wired into
store-artifact/content_resolver.py).

`network_prefix` (config) maps to pybatfish's own `network` parameter on the
`routes()` question (a route-prefix filter, e.g. "192.168.1.0/24") --
`BatfishService.routes()` takes the Batfish network name as `batfish_network`
specifically so this doesn't collide with that.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_routes
from workflow_steps.batfish_routing_table.config import get_config
from workflow_steps.common.batfish_context import devices_from_nodes, resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_results import store_batfish_result
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.run_logging import log_run_id

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-routing-table"


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
    output_key = parse_output_key_config(
        merged_config.get("output_key"),
        step_id=_STEP_ID,
        default="batfish_routes",
        key_name="output_key",
    )
    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s",
        _STEP_ID,
        log_run_id(run),
        node_id,
        snap.network,
        snap.snapshot,
    )

    rows = await query_routes(
        batfish,
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=merged_config.get("nodes"),
        network_prefix=merged_config.get("network_prefix"),
        prefix_match_type=merged_config.get("prefix_match_type"),
        protocols=merged_config.get("protocols"),
        vrfs=merged_config.get("vrfs"),
        rib=merged_config.get("rib"),
    )

    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = await store_batfish_result(
        artifact_service,
        rows,
        context=context,
        node_id=node_id,
        question="routes",
        row_count=len(rows),
    )

    logger.info("%s finished run_id=%s rows=%d", _STEP_ID, log_run_id(run), len(rows))

    device_nodes = devices_from_nodes(rows)

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{len(rows)} route(s)",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]
