"""Executor for the batfish-start-run step ("Get from Batfish").

Three-way auto-detected behavior, no mode/toggle config field -- see
doc/BATFISH_INTEGRATION.md "Get from Batfish" for the full explanation:

1. Unconfigured AND no run metadata resolvable (context.metadata["batfish"]
   absent, and neither batfish_source_id nor network configured): today's
   original placeholder behavior, unchanged -- context.devices is
   unconditionally cleared to {} and success fires, with ZERO Batfish calls.
   This preserves this step's original role: letting a git-mode Init Batfish
   Snapshot step (which needs no live devices) satisfy the canvas's
   requires: [identity] connection rule (see workflow-canvas.tsx::
   isValidConnection).
2. context.metadata["batfish"] present (this step ran after this run's own
   Init Batfish Snapshot): resolves that snapshot, queries nodeProperties
   for every matching node, and REPLACES context.devices with one
   Batfish-sourced DeviceContext per distinct node -- same "always replace,
   never merge" contract as other Get-from-X device-selection steps
   (get-from-list, get-nautobot-devices).
3. batfish_source_id + network both configured: targets that standing
   network directly (the documented "production pattern"), bypassing this
   run's metadata entirely, same replace-devices behavior as (2).

A workflow may legitimately contain two instances of this step: one before
Init Batfish Snapshot (case 1, placeholder) and one after it (case 2, real
device population).

Critical: resolve_batfish_snapshot_ref (and the resolve_batfish_snapshot it
falls back to) always raises ValueError when nothing is resolvable -- it
never returns a falsy sentinel. So case (1)'s precondition is checked here,
BEFORE calling it, rather than by catching ValueError -- a blanket except
would also swallow genuine misconfiguration (malformed metadata, a
nonexistent network, a network with no snapshots), which must propagate as
a real step failure, not be silently treated as "no devices."
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_node_properties
from workflow_steps.batfish_start_run.config import get_config
from workflow_steps.common.batfish_context import devices_from_nodes, resolve_batfish_snapshot_ref

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-start-run"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: no artifact written, no SSH

    merged_config = {**get_config(), **config}
    source_id = str(merged_config.get("batfish_source_id") or "").strip()
    network = str(merged_config.get("network") or "").strip()
    direct_target_configured = bool(source_id and network)
    metadata_present = isinstance(context.metadata.get("batfish"), dict)

    if not direct_target_configured and not metadata_present:
        logger.info(
            "%s run_id=%s node_id=%s: nothing configured, clearing devices",
            _STEP_ID,
            run.id,
            node_id,
        )
        return [
            StepOutcome(name="success", context=context.model_copy(update={"devices": {}}))
        ]

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
        nodes=merged_config.get("nodes_filter"),
    )
    device_nodes = devices_from_nodes(rows)

    logger.info("%s finished run_id=%s devices=%d", _STEP_ID, run.id, len(device_nodes))

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        )
    ]
