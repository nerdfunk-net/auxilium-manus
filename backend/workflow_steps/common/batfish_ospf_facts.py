"""Merge/storage entry point for the batfish-ospf-facts step: combines up to
four Batfish OSPF questions (ospfProcessConfiguration, ospfAreaConfiguration,
ospfInterfaceConfiguration, ospfEdges) into one per-device OSPF picture.

The actual fetch-store-merge engine lives in
workflow_steps.common.batfish_combined_facts (shared with Get BGP Facts,
see workflow_steps.common.batfish_bgp_facts). The OSPF-specific
`CombinedQuestionSpec` table itself now lives in
`services.batfish.ospf_facts` (re-exported here for backward-compatible
imports) so `services.batfish.preview_service` can build the ad-hoc "Get
OSPF Facts" preview from the exact same spec table -- see that module's
docstring, and doc/BATFISH_INTEGRATION.md "Batfish OSPF Facts" for the
row-shape verification it's built on.
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.ospf_facts import OSPF_QUESTION_KEYS, OSPF_QUESTION_SPECS
from workflow_steps.common.batfish_combined_facts import build_combined_facts_outcomes

__all__ = ["OSPF_QUESTION_KEYS", "OSPF_QUESTION_SPECS", "build_ospf_facts_outcomes"]

_STEP_ID = "batfish-ospf-facts"


async def build_ospf_facts_outcomes(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> list[StepOutcome]:
    return await build_combined_facts_outcomes(
        step_id=_STEP_ID,
        specs=OSPF_QUESTION_SPECS,
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        rows_by_question=rows_by_question,
    )
