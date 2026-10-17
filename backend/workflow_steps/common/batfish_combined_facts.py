"""Generic engine behind the "combined facts" Batfish steps (Get OSPF Facts,
Get BGP Facts, ...): make up to N Batfish calls, store one artifact per
enabled question (same `kind: "batfish_result"` convention every other
Batfish step uses), and merge all enabled questions' rows into one payload
per device.

`CombinedQuestionSpec` and the per-node merge logic itself now live in
`services.batfish.facts_specs` (re-exported here for backward-compatible
imports) -- moved there so `services.batfish.preview_service` can build the
ad-hoc "Get OSPF/BGP Facts" preview from the exact same merge logic, without
a service importing from `workflow_steps` (see that module's docstring).

Extracted from workflow_steps.common.batfish_ospf_facts once a second
consumer (Get BGP Facts) needed the identical merge/storage mechanics with a
different question set and different per-question grouping/shaping rules --
see that module and workflow_steps.common.batfish_bgp_facts for the two
current `CombinedQuestionSpec` tables. Unlike
workflow_steps.common.batfish_properties (one Batfish call in, one result
out), every consumer here makes several calls and merges them per node --
genuinely different merge logic, not another PropertyQuestionSpec entry.

`rows_by_question` passed to `build_combined_facts_outcomes` carries only the
ENABLED questions for a given run -- a question the step config disabled is
simply absent from both the stored artifacts and the merged per-device
payload, never present with a null/empty value.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.batfish.facts_specs import CombinedQuestionSpec, merge_facts_by_node

__all__ = ["CombinedQuestionSpec", "build_combined_facts_outcomes"]

logger = logging.getLogger(__name__)


async def build_combined_facts_outcomes(
    *,
    step_id: str,
    specs: dict[str, CombinedQuestionSpec],
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> list[StepOutcome]:
    metadata = dict(context.metadata)
    summary_parts: list[str] = []

    for key, rows in rows_by_question.items():
        spec = specs[key]
        content = json.dumps(rows, indent=2, default=str)
        artifact_ref = await artifact_service.store(
            content=content,
            kind="batfish_result",
            device_id=f"batfish-{node_id}",
            run_id=context.run_id,
            media_type="application/json",
        )
        metadata[f"{node_id}.{output_key}.{key}"] = {
            "kind": "batfish_result",
            "question": spec.question_label,
            "artifact_ref": artifact_ref.model_dump(mode="json"),
            "row_count": len(rows),
        }
        summary_parts.append(f"{len(rows)} {spec.row_noun}")

    payloads_by_node = merge_facts_by_node(specs, rows_by_question)
    device_nodes: dict[str, DeviceContext] = {}
    for node, parsed_payload in payloads_by_node.items():
        device = DeviceContext(
            id=node,
            name=node,
            hostname=node,
            source="batfish",
            capabilities={Capability.IDENTITY, Capability.PARSED},
            status=DeviceStatus.OK,
        )
        device_nodes[node] = device.model_copy(
            update={
                "parsed": {node_id: {output_key: {"parsed": parsed_payload, "error": None}}}
            }
        )

    logger.info(
        "%s finished run_id=%s node_id=%s questions=%s devices=%d",
        step_id,
        context.run_id,
        node_id,
        sorted(rows_by_question),
        len(device_nodes),
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary="; ".join(summary_parts) if summary_parts else "0 rows",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]
