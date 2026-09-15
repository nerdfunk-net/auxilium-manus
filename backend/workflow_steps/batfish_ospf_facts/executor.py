"""Executor for the batfish-ospf-facts step ("Get OSPF Facts").

Combines up to four Batfish OSPF questions --
ospfProcessConfiguration/ospfAreaConfiguration/ospfInterfaceConfiguration/
ospfEdges -- against the snapshot an upstream batfish-init-snapshot step
initialized (resolved via workflow_steps.common.batfish_context), each
individually toggleable. Pure read -- does not touch context.devices as
input.

Everything past "fetch each enabled question's rows" (per-question artifact
storage, node-identity grouping, and the per-device merge into one combined
OSPF payload) lives in workflow_steps.common.batfish_ospf_facts -- see that
module's docstring for the full reasoning and doc/BATFISH_INTEGRATION.md
"Batfish OSPF Facts" for the row-shape verification this is built on.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.query_helpers import (
    query_ospf_area_configuration,
    query_ospf_edges,
    query_ospf_interface_configuration,
    query_ospf_process_configuration,
)
from workflow_steps.batfish_ospf_facts.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_ospf_facts import OSPF_QUESTION_KEYS, build_ospf_facts_outcomes

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-ospf-facts"

# Each question key maps to a config toggle named f"include_{key}" -- derived
# from OSPF_QUESTION_KEYS (single source of truth for the question set,
# shared with the merge engine) rather than hand-listed here too.
_QUESTION_TOGGLES: tuple[tuple[str, str], ...] = tuple(
    (f"include_{key}", key) for key in OSPF_QUESTION_KEYS
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
    enabled_keys = [
        question_key
        for toggle_key, question_key in _QUESTION_TOGGLES
        if bool(merged_config.get(toggle_key, True))
    ]
    if not enabled_keys:
        raise ValueError(
            f"{_STEP_ID}: at least one of include_process/include_areas/"
            "include_interfaces/include_edges must be enabled"
        )

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s questions=%s",
        _STEP_ID,
        run.id,
        node_id,
        snap.network,
        snap.snapshot,
        enabled_keys,
    )

    nodes = merged_config.get("nodes")
    rows_by_question: dict[str, list[dict[str, Any]]] = {}
    if "process" in enabled_keys:
        rows_by_question["process"] = await query_ospf_process_configuration(
            batfish, snap.connection, batfish_network=snap.network, snapshot=snap.snapshot,
            nodes=nodes,
        )
    if "areas" in enabled_keys:
        rows_by_question["areas"] = await query_ospf_area_configuration(
            batfish, snap.connection, batfish_network=snap.network, snapshot=snap.snapshot,
            nodes=nodes,
        )
    if "interfaces" in enabled_keys:
        rows_by_question["interfaces"] = await query_ospf_interface_configuration(
            batfish, snap.connection, batfish_network=snap.network, snapshot=snap.snapshot,
            nodes=nodes,
        )
    if "edges" in enabled_keys:
        rows_by_question["edges"] = await query_ospf_edges(
            batfish, snap.connection, batfish_network=snap.network, snapshot=snap.snapshot,
            nodes=nodes,
        )

    output_key = str(
        merged_config.get("output_key") or "batfish_ospf_facts"
    ).strip() or "batfish_ospf_facts"

    return await build_ospf_facts_outcomes(
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        rows_by_question=rows_by_question,
    )
