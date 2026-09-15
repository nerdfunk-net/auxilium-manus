"""Shared per-node "combine Batfish question rows into one payload" engine.

Used by two families of workflow steps -- the "combined facts" steps (Get
OSPF Facts, Get BGP Facts: up to 4 questions merged into one per-node
picture, see `ospf_facts.py`/`bgp_facts.py`) and the "property lookup"
steps (Batfish Node/Interface Properties: one question, grouped by node) --
AND by `services.batfish.preview_service.BatfishPreviewService`'s ad-hoc
preview endpoints for those same steps plus Extract Facts, so the Template
Editor's ad-hoc preview produces byte-for-byte the same per-node payload
shape a real workflow run would write into
``device.parsed[output_key]["parsed"]``.

Lives in `services/batfish/` (not `workflow_steps/common/`) specifically so
the preview service can import it: this codebase's convention is that
external code never imports `workflow_steps` packages directly (only
`StepRunner` calls executors -- see CLAUDE.md), so anything a service needs
to share with the workflow steps lives here, on the services side of that
boundary. Mirrors `query_helpers.py`, already "shared by workflow-step
executors AND BatfishPreviewService" for the single-question case; this
module is the same idea for the "combine N questions"/"group one question
by node" cases.

`CombinedQuestionSpec`/`PropertyQuestionSpec` themselves, and
`group_rows_by_node`, were moved here verbatim from
`workflow_steps.common.batfish_combined_facts`/`batfish_properties` --
those modules now import them from here. `merge_facts_by_node` is new,
extracted from `build_combined_facts_outcomes`'s own per-device merge loop
so both the real "devices" outcome and an ad-hoc preview build the
identical shape from the identical logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CombinedQuestionSpec:
    """One Batfish question a "combined facts" step (or its ad-hoc preview
    counterpart) knows how to fetch, group, and merge.

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


@dataclass(frozen=True)
class PropertyQuestionSpec:
    """One Batfish "property lookup" question (Node/Interface Properties).

    - `question_label`: stored verbatim in the result metadata's `question`
      field (e.g. "nodeProperties").
    - `node_key`: given one row, returns the node name it belongs to (or
      None to skip it).
    - `build_parsed_for_node`: given every row belonging to one node,
      returns that node's own `parsed[...]["parsed"]` payload -- the one
      place the node-shaped vs. interface-shaped nesting differs.
    - `row_noun`: cosmetic only, used in the `success` outcome's summary text
      (e.g. "node(s)" / "interface(s)").
    """

    question_label: str
    node_key: Callable[[dict[str, Any]], str | None]
    build_parsed_for_node: Callable[[list[dict[str, Any]]], dict[str, Any]]
    row_noun: str


def group_rows_by_node(
    rows: list[dict[str, Any]], *, node_key: Callable[[dict[str, Any]], str | None]
) -> dict[str, list[dict[str, Any]]]:
    """Group a Batfish answer's rows by node identity, dropping rows with no
    resolvable node."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        node = node_key(row)
        if not node:
            continue
        grouped.setdefault(node, []).append(row)
    return grouped


def merge_facts_by_node(
    specs: dict[str, CombinedQuestionSpec],
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Merge every enabled question's rows into one payload per node --
    ``{node: {parsed_field: build_group_value(that node's rows), ...}}``,
    only enabled questions' `parsed_field`s present for a given node. This is
    exactly the shape `batfish-ospf-facts`/`batfish-bgp-facts` write into
    ``device.parsed[output_key]["parsed"]`` on their ``devices`` outcome, and
    what the ad-hoc preview endpoint returns as `facts_by_node`.
    """
    grouped_by_question = {
        key: group_rows_by_node(rows, node_key=specs[key].node_key)
        for key, rows in rows_by_question.items()
    }

    all_nodes: set[str] = set()
    for grouped in grouped_by_question.values():
        all_nodes.update(grouped.keys())

    result: dict[str, dict[str, Any]] = {}
    for node in all_nodes:
        payload: dict[str, Any] = {}
        for key, grouped in grouped_by_question.items():
            node_rows = grouped.get(node)
            if not node_rows:
                continue
            spec = specs[key]
            payload[spec.parsed_field] = spec.build_group_value(node_rows)
        result[node] = payload
    return result


def facts_by_node_for_property(
    spec: PropertyQuestionSpec, rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Group a single property question's rows by node and apply
    ``build_parsed_for_node`` -- the per-node payload shape
    ``batfish-node-properties``/``batfish-interface-properties`` write into
    ``device.parsed[output_key]["parsed"]`` on their ``devices`` outcome,
    and what the ad-hoc preview endpoint returns as `facts_by_node`.
    """
    grouped = group_rows_by_node(rows, node_key=spec.node_key)
    return {node: spec.build_parsed_for_node(node_rows) for node, node_rows in grouped.items()}
