"""Executor for the batfish-acl-check step.

Wraps Batfish's `testFilters` question -- "does this specific 5-tuple flow
get permitted or denied by this named filter/ACL on this node" -- against
the snapshot an upstream batfish-init-snapshot step initialized. Like
Path Check, this evaluates ONE concrete flow taken from `config`, not one
check per device, so it returns a single-element list[StepOutcome] carrying
the full, unmodified context.devices through. See
doc/BATFISH_INTEGRATION.md "Batfish ACL Check".

`searchFilters` was considered and rejected for this step -- it answers a
broader "does ANY matching flow get through" existence question, whereas
"ACL permits this traffic" reads as "check this specific traffic
description," which is testFilters()'s contract.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import query_test_filters, require_field
from workflow_steps.batfish_acl_check.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-acl-check"


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
    node = require_field(merged_config.get("node"), "node")
    filter_name = require_field(merged_config.get("filter_name"), "filter_name")
    dst_ips = require_field(merged_config.get("dst_ips"), "dst_ips")

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s node=%s filter=%s",
        _STEP_ID,
        run.id,
        node_id,
        snap.network,
        snap.snapshot,
        node,
        filter_name,
    )

    rows, action = await query_test_filters(
        batfish,
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        node=node,
        filter_name=filter_name,
        dst_ips=dst_ips,
        src_ips=merged_config.get("src_ips"),
        applications=merged_config.get("applications"),
        ip_protocols=merged_config.get("ip_protocols"),
        start_location=merged_config.get("start_location"),
    )

    permitted = action == "PERMIT"
    output_key = str(merged_config.get("output_key") or "batfish_acl_check").strip() or (
        "batfish_acl_check"
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
        "question": "testFilters",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(rows),
        "action": action,
    }

    logger.info("%s finished run_id=%s action=%s", _STEP_ID, run.id, action)

    outcome_name = "permit" if permitted else "deny"
    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{outcome_name} ({action})",
        )
    ]
