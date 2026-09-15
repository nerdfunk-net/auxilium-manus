"""Question specs for the batfish-bgp-facts step: combines up to four
Batfish BGP questions (bgpProcessConfiguration, bgpPeerConfiguration,
bgpSessionStatus, bgpEdges) into one per-device BGP picture.

The actual fetch-store-merge engine lives in
workflow_steps.common.batfish_combined_facts (shared with Get OSPF Facts,
see workflow_steps.common.batfish_ospf_facts) -- this module only supplies
the BGP-specific `CombinedQuestionSpec` table. See
doc/BATFISH_INTEGRATION.md "Batfish BGP Facts" for the row-shape
verification this is built on.

**Simpler than OSPF: all four questions share one identity shape.** Unlike
OSPF (two questions plain-`Node`, two nested-`Interface`), every one of
these four BGP questions returns a plain `Node` string column -- confirmed
live against a synthetic 3-router eBGP snapshot (r1-AS100 -- r2-AS200 --
r3-AS300). `bgpSessionStatus`/`bgpEdges` carry a `Remote_Node` field
alongside `Node`, but -- same design choice as `ospfEdges`' `Remote_Interface`
-- that's additional data on the *local* node's row, not a second identity
to resolve; a node appearing only as another node's `Remote_Node` does not
get its own device.

Multi-row-per-node is the normal case for every one of these four questions
(a node with more than one peer/session/adjacency, or more than one VRF's
BGP process), so every question's merged value is always a list, never a
single dict -- same reasoning as OSPF's Process/Areas.
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.batfish_combined_facts import (
    CombinedQuestionSpec,
    build_combined_facts_outcomes,
)

_STEP_ID = "batfish-bgp-facts"


def _node_key(row: dict[str, Any]) -> str | None:
    return row.get("Node")


def _strip_node(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k != "Node"} for row in rows]


BGP_QUESTION_SPECS: dict[str, CombinedQuestionSpec] = {
    "process": CombinedQuestionSpec(
        key="process",
        question_label="bgpProcessConfiguration",
        parsed_field="Process",
        node_key=_node_key,
        build_group_value=_strip_node,
        row_noun="process row(s)",
    ),
    "peers": CombinedQuestionSpec(
        key="peers",
        question_label="bgpPeerConfiguration",
        parsed_field="Peers",
        node_key=_node_key,
        build_group_value=_strip_node,
        row_noun="peer row(s)",
    ),
    "sessions": CombinedQuestionSpec(
        key="sessions",
        question_label="bgpSessionStatus",
        parsed_field="Sessions",
        node_key=_node_key,
        build_group_value=_strip_node,
        row_noun="session row(s)",
    ),
    "edges": CombinedQuestionSpec(
        key="edges",
        question_label="bgpEdges",
        parsed_field="Adjacencies",
        node_key=_node_key,
        build_group_value=_strip_node,
        row_noun="adjacency row(s)",
    ),
}

# Question keys, in the order the frontend checkboxes present them. Each
# maps to a step config toggle named f"include_{key}" -- the executor derives
# its toggle table from this instead of hand-listing the same four keys
# again, so adding/removing a question only needs one edit here.
BGP_QUESTION_KEYS: tuple[str, ...] = ("process", "peers", "sessions", "edges")


async def build_bgp_facts_outcomes(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> list[StepOutcome]:
    return await build_combined_facts_outcomes(
        step_id=_STEP_ID,
        specs=BGP_QUESTION_SPECS,
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        rows_by_question=rows_by_question,
    )
