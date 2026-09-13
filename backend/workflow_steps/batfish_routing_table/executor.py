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

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.batfish_routing_table.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-routing-table"


def _or_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


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
    snap = resolve_batfish_snapshot(context)
    batfish = service_factory.get_batfish_app_service()

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        snap.network,
        snap.snapshot,
    )

    rows = await batfish.routes(
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=_or_none(merged_config.get("nodes")),
        network=_or_none(merged_config.get("network_prefix")),
        prefixMatchType=_or_none(merged_config.get("prefix_match_type")),
        protocols=_or_none(merged_config.get("protocols")),
        vrfs=_or_none(merged_config.get("vrfs")),
        rib=_or_none(merged_config.get("rib")),
    )

    output_key = str(merged_config.get("output_key") or "batfish_routes").strip() or (
        "batfish_routes"
    )

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
        "question": "routes",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(rows),
    }

    logger.info("%s finished run_id=%s rows=%d", _STEP_ID, run.id, len(rows))

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{len(rows)} route(s)",
        )
    ]
