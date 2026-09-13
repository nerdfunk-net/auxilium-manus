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
from workflow_steps.batfish_acl_check.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-acl-check"


def _build_headers(config: dict[str, Any], dst_ips: str) -> dict[str, Any]:
    headers: dict[str, Any] = {"dstIps": dst_ips}
    src_ips = str(config.get("src_ips") or "").strip()
    if src_ips:
        headers["srcIps"] = src_ips
    applications = config.get("applications")
    if applications:
        headers["applications"] = applications
    ip_protocols = str(config.get("ip_protocols") or "").strip()
    if ip_protocols:
        headers["ipProtocols"] = ip_protocols
    return headers


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
    node = str(merged_config.get("node") or "").strip()
    if not node:
        raise ValueError(f"{_STEP_ID}: node is required")
    filter_name = str(merged_config.get("filter_name") or "").strip()
    if not filter_name:
        raise ValueError(f"{_STEP_ID}: filter_name is required")
    dst_ips = str(merged_config.get("dst_ips") or "").strip()
    if not dst_ips:
        raise ValueError(f"{_STEP_ID}: dst_ips is required")

    snap = resolve_batfish_snapshot(context)
    batfish = service_factory.get_batfish_app_service()
    headers = _build_headers(merged_config, dst_ips)
    start_location = str(merged_config.get("start_location") or "").strip() or None

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

    rows = await batfish.test_filters(
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=node,
        filters=filter_name,
        headers=headers,
        startLocation=start_location,
    )

    if not rows:
        raise RuntimeError(
            f"{_STEP_ID}: no result returned -- check that node/filter_name match the snapshot"
        )

    action = str(rows[0].get("Action", "")).strip().upper()
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
