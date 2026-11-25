"""Executor for the batfish-bgp-facts step ("Get BGP Facts").

Combines up to four Batfish BGP questions (bgpProcessConfiguration, bgpPeerConfiguration,
bgpSessionStatus, bgpEdges),
each individually toggleable (``include_<key>``), against the snapshot an upstream
batfish-init-snapshot step initialized. Pure read; it does not use ``context.devices`` as input.
The body (queries, artifact per question, per-node merge) is
``common.batfish_combined_facts.run_combined_facts_step``; this module is the question table.
See doc/BATFISH_INTEGRATION.md "Batfish BGP Facts" for the row-shape verification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.bgp_facts import BGP_QUESTION_SPECS
from services.batfish.query_helpers import (
    query_bgp_edges,
    query_bgp_peer_configuration,
    query_bgp_process_configuration,
    query_bgp_session_status,
)
from workflow_steps.batfish_bgp_facts.config import get_config
from workflow_steps.common.batfish_combined_facts import run_combined_facts_step

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

_STEP_ID = "batfish-bgp-facts"

_QUERIES = {
    "process": query_bgp_process_configuration,
    "peers": query_bgp_peer_configuration,
    "sessions": query_bgp_session_status,
    "edges": query_bgp_edges,
}


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

    return await run_combined_facts_step(
        step_id=_STEP_ID,
        specs=BGP_QUESTION_SPECS,
        queries=_QUERIES,
        default_output_key="batfish_bgp_facts",
        default_config=get_config(),
        config=config,
        context=context,
        run=run,
        artifact_service=artifact_service,
        node_id=node_id,
    )
