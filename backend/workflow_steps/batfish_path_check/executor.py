"""Executor for the batfish-path-check step.

Wraps Batfish's `reachability` question -- "is there a path between device A
and device B (optionally matching a header space)" -- against the snapshot
an upstream batfish-init-snapshot step initialized. Evaluates ONE flow
definition taken from `config`, not one check per device in
context.devices, so this step returns a single-element list[StepOutcome]
(whichever of reachable/not_reachable applies) carrying the full,
unmodified context.devices through -- unlike compare-pyats-snapshot's
per-device match/mismatch/failure buckets, there is nothing here to
partition devices by. See doc/BATFISH_INTEGRATION.md "Batfish Path Check".

IMPORTANT param-shape gotcha (verified against a live coordinator): `headers`
is a sibling top-level parameter of `pathConstraints`, not nested inside it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.batfish_path_check.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-path-check"


def _build_headers(config: dict[str, Any]) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    dst_ips = str(config.get("dst_ips") or "").strip()
    if dst_ips:
        headers["dstIps"] = dst_ips
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
    start_node = str(merged_config.get("start_node") or "").strip()
    if not start_node:
        raise ValueError(f"{_STEP_ID}: start_node is required")

    snap = resolve_batfish_snapshot(context)
    batfish = service_factory.get_batfish_app_service()

    path_constraints: dict[str, Any] = {"startLocation": start_node}
    end_node = str(merged_config.get("end_node") or "").strip()
    if end_node:
        path_constraints["endLocation"] = end_node

    headers = _build_headers(merged_config)

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s start=%s end=%s",
        _STEP_ID,
        run.id,
        node_id,
        snap.network,
        snap.snapshot,
        start_node,
        end_node or None,
    )

    rows = await batfish.reachability(
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        pathConstraints=path_constraints,
        headers=headers or None,
        maxTraces=merged_config.get("max_traces"),
        invertSearch=bool(merged_config.get("invert_search", False)),
        ignoreFilters=bool(merged_config.get("ignore_filters", False)),
    )

    reachable = len(rows) > 0
    output_key = str(merged_config.get("output_key") or "batfish_path_check").strip() or (
        "batfish_path_check"
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
        "question": "reachability",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(rows),
        "reachable": reachable,
    }

    logger.info(
        "%s finished run_id=%s reachable=%s rows=%d", _STEP_ID, run.id, reachable, len(rows)
    )

    outcome_name = "reachable" if reachable else "not_reachable"
    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{outcome_name} ({len(rows)} flow(s))",
        )
    ]
