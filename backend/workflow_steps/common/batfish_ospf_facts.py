"""Shared engine for the batfish-ospf-facts step: combines up to four Batfish
OSPF questions (ospfProcessConfiguration, ospfAreaConfiguration,
ospfInterfaceConfiguration, ospfEdges) into one per-device OSPF picture.

Unlike workflow_steps.common.batfish_properties (one Batfish call in, one
result out), this step makes up to four calls and merges them per node --
genuinely different merge logic, not another PropertyQuestionSpec entry. See
doc/BATFISH_INTEGRATION.md "Batfish OSPF Facts" for the row-shape
verification this is built on (all four questions were confirmed live
against a synthetic multi-area/multi-VRF snapshot, including the multi-row-
per-node cases below).

Row-identity shapes (both already known to batfish_properties.py, reused
here via group_rows_by_node):
- ospfProcessConfiguration / ospfAreaConfiguration: plain "Node" string
  column, same shape as nodeProperties.
- ospfInterfaceConfiguration / ospfEdges: nested "Interface" dict column
  ({"hostname": ..., "interface": ...}), same shape as interfaceProperties.

Multi-row-per-node is the normal case for two of these four questions, not
an edge case: a node running OSPF in more than one VRF gets more than one
ospfProcessConfiguration row, and an ABR spanning more than one area gets
more than one ospfAreaConfiguration row -- both confirmed live. So "Process"
and "Areas" are always lists in the merged payload, never a single dict
(which would silently drop data for exactly those nodes).
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


def _node_key(row: dict[str, Any]) -> str | None:
    return row.get("Node")


def _interface_node_key(row: dict[str, Any]) -> str | None:
    interface = row.get("Interface")
    return interface.get("hostname") if isinstance(interface, dict) else None


def _strip_key(rows: list[dict[str, Any]], *, drop: str) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k != drop} for row in rows]


def _build_interfaces_dict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One entry per interface name -- same nesting convention
    batfish-interface-properties already uses for ospfInterfaceConfiguration's
    identical row shape."""
    interfaces: dict[str, dict[str, Any]] = {}
    for row in rows:
        interface = row.get("Interface")
        name = interface.get("interface") if isinstance(interface, dict) else None
        if not name:
            continue
        interfaces[str(name)] = {key: value for key, value in row.items() if key != "Interface"}
    return interfaces


@dataclass(frozen=True)
class OspfQuestionSpec:
    """One OSPF question this engine knows how to fetch, group, and merge.

    - `key`: the question's slot in step config/rows_by_question (e.g.
      "process") -- also used to namespace its artifact's metadata key.
    - `question_label`: the real Batfish question name, stored verbatim in
      the artifact's `question` field (e.g. "ospfProcessConfiguration").
    - `parsed_field`: the key this question's merged value is nested under
      in a device's combined OSPF payload (e.g. "Process").
    - `node_key`: identity extractor for this question's rows.
    - `build_group_value`: given every row belonging to one node, returns
      that node's own value for `parsed_field` -- a list for
      process/areas/edges (more than one row per node is the normal case for
      process/areas; a node can have several adjacencies), a dict keyed by
      interface name for interfaces (mirrors batfish-interface-properties).
    - `row_noun`: cosmetic only, used in the `success` outcome's summary.
    """

    key: str
    question_label: str
    parsed_field: str
    node_key: Callable[[dict[str, Any]], str | None]
    build_group_value: Callable[[list[dict[str, Any]]], Any]
    row_noun: str


OSPF_QUESTION_SPECS: dict[str, OspfQuestionSpec] = {
    "process": OspfQuestionSpec(
        key="process",
        question_label="ospfProcessConfiguration",
        parsed_field="Process",
        node_key=_node_key,
        build_group_value=lambda rows: _strip_key(rows, drop="Node"),
        row_noun="process row(s)",
    ),
    "areas": OspfQuestionSpec(
        key="areas",
        question_label="ospfAreaConfiguration",
        parsed_field="Areas",
        node_key=_node_key,
        build_group_value=lambda rows: _strip_key(rows, drop="Node"),
        row_noun="area row(s)",
    ),
    "interfaces": OspfQuestionSpec(
        key="interfaces",
        question_label="ospfInterfaceConfiguration",
        parsed_field="Interfaces",
        node_key=_interface_node_key,
        build_group_value=_build_interfaces_dict,
        row_noun="interface row(s)",
    ),
    "edges": OspfQuestionSpec(
        key="edges",
        question_label="ospfEdges",
        parsed_field="Adjacencies",
        node_key=_interface_node_key,
        build_group_value=lambda rows: list(rows),
        row_noun="adjacency row(s)",
    ),
}

# Question keys, in the order the frontend checkboxes present them. Each
# maps to a step config toggle named f"include_{key}" -- the executor derives
# its toggle table from this instead of hand-listing the same four keys
# again, so adding/removing a question only needs one edit here.
OSPF_QUESTION_KEYS: tuple[str, ...] = ("process", "areas", "interfaces", "edges")


async def build_ospf_facts_outcomes(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> list[StepOutcome]:
    """Store one artifact per enabled question (same `kind: "batfish_result"`
    convention every other Batfish step uses -- each shows up automatically
    in the run viewer), then merge all enabled questions' rows into one
    combined OSPF payload per device.

    `rows_by_question` carries only the ENABLED questions -- a question the
    step config disabled is simply absent from both the stored artifacts and
    the merged per-device payload, not present with a null/empty value.
    """
    metadata = dict(context.metadata)
    grouped_by_question: dict[str, dict[str, list[dict[str, Any]]]] = {}
    summary_parts: list[str] = []

    for key, rows in rows_by_question.items():
        spec = OSPF_QUESTION_SPECS[key]
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
            spec = OSPF_QUESTION_SPECS[key]
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
        "batfish-ospf-facts finished run_id=%s node_id=%s questions=%s devices=%d",
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
