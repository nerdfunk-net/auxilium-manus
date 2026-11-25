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

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.common.exceptions import BatfishAnswerFailedError
from services.batfish.query_helpers import query_test_filters, require_field
from workflow_steps.batfish_acl_check.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_results import store_batfish_result
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.run_logging import log_run_id

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
    output_key = parse_output_key_config(
        merged_config.get("output_key"),
        step_id=_STEP_ID,
        default="batfish_acl_check",
        key_name="output_key",
    )
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
        log_run_id(run),
        node_id,
        snap.network,
        snap.snapshot,
        node,
        filter_name,
    )

    try:
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
    except BatfishAnswerFailedError as exc:
        raise ValueError(
            f"Batfish could not evaluate filter {filter_name!r} on node={node!r} -- "
            "this usually means the device or filter is not known to this Batfish "
            "snapshot (check for a typo, or that the device has been collected "
            "into the snapshot)."
        ) from exc

    permitted = action == "PERMIT"

    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = await store_batfish_result(
        artifact_service,
        rows,
        context=context,
        node_id=node_id,
        question="testFilters",
        row_count=len(rows),
        action=action,
    )

    logger.info("%s finished run_id=%s action=%s", _STEP_ID, log_run_id(run), action)

    outcome_name = "permit" if permitted else "deny"
    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{outcome_name} ({action})"
            + (f", {len(rows)} filters" if len(rows) > 1 else ""),
        )
    ]
