"""Generic engine behind the "combined facts" Batfish steps (Get OSPF Facts,
Get BGP Facts, ...): make up to N Batfish calls, store one artifact per
enabled question (same `kind: "batfish_result"` convention every other
Batfish step uses), and merge all enabled questions' rows into one payload
per device.

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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.batfish_properties import group_rows_by_node

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CombinedQuestionSpec:
    """One Batfish question a "combined facts" step knows how to fetch,
    group, and merge.

    - `key`: the question's slot in step config/rows_by_question (e.g.
      "process") -- also used to namespace its artifact's metadata key.
    - `question_label`: the real Batfish question name, stored verbatim in
      the artifact's `question` field (e.g. "ospfProcessConfiguration").
    - `parsed_field`: the key this question's merged value is nested under
      in a device's combined payload (e.g. "Process").
    - `node_key`: identity extractor for this question's rows.
    - `build_group_value`: given every row belonging to one node, returns
      that node's own value for `parsed_field` -- typically a list (more
      than one row per node is the normal case for most of these questions),
      but a dict keyed by a secondary identity (e.g. interface name) where
      the question naturally supports one.
    - `row_noun`: cosmetic only, used in the `success` outcome's summary.
    """

    key: str
    question_label: str
    parsed_field: str
    node_key: Callable[[dict[str, Any]], str | None]
    build_group_value: Callable[[list[dict[str, Any]]], Any]
    row_noun: str


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
    grouped_by_question: dict[str, dict[str, list[dict[str, Any]]]] = {}
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
        grouped_by_question[key] = group_rows_by_node(rows, node_key=spec.node_key)
        summary_parts.append(f"{len(rows)} {spec.row_noun}")

    all_nodes: set[str] = set()
    for grouped in grouped_by_question.values():
        all_nodes.update(grouped.keys())

    parsed_key = f"{node_id}.{output_key}"
    device_nodes: dict[str, DeviceContext] = {}
    for node in all_nodes:
        parsed_payload: dict[str, Any] = {}
        for key, grouped in grouped_by_question.items():
            node_rows = grouped.get(node)
            if not node_rows:
                continue
            spec = specs[key]
            parsed_payload[spec.parsed_field] = spec.build_group_value(node_rows)

        device = DeviceContext(
            id=node,
            name=node,
            hostname=node,
            source="batfish",
            capabilities={Capability.IDENTITY, Capability.PARSED},
            status=DeviceStatus.OK,
        )
        device_nodes[node] = device.model_copy(
            update={"parsed": {parsed_key: {"parsed": parsed_payload, "error": None}}}
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
