"""Question specs for OSPF "combined facts": combines up to four Batfish
OSPF questions (ospfProcessConfiguration, ospfAreaConfiguration,
ospfInterfaceConfiguration, ospfEdges) into one per-node OSPF picture.

Shared by the `batfish-ospf-facts` workflow step
(`workflow_steps.common.batfish_ospf_facts`, which re-exports
`OSPF_QUESTION_SPECS`/`OSPF_QUESTION_KEYS` from here) and
`services.batfish.preview_service.BatfishPreviewService`'s ad-hoc "Get OSPF
Facts" preview. See `doc/BATFISH_INTEGRATION.md` "Batfish OSPF Facts" for
the row-shape verification this is built on (all four questions were
confirmed live against a synthetic multi-area/multi-VRF snapshot, including
the multi-row-per-node cases below).

Row-identity shapes (both already known to `node_properties_spec.py`/
`interface_properties_spec.py`, reused here via `group_rows_by_node` inside
`merge_facts_by_node`):
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

from typing import Any

from services.batfish.facts_specs import CombinedQuestionSpec


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


OSPF_QUESTION_SPECS: dict[str, CombinedQuestionSpec] = {
    "process": CombinedQuestionSpec(
        key="process",
        question_label="ospfProcessConfiguration",
        parsed_field="Process",
        node_key=_node_key,
        build_group_value=lambda rows: _strip_key(rows, drop="Node"),
        row_noun="process row(s)",
    ),
    "areas": CombinedQuestionSpec(
        key="areas",
        question_label="ospfAreaConfiguration",
        parsed_field="Areas",
        node_key=_node_key,
        build_group_value=lambda rows: _strip_key(rows, drop="Node"),
        row_noun="area row(s)",
    ),
    "interfaces": CombinedQuestionSpec(
        key="interfaces",
        question_label="ospfInterfaceConfiguration",
        parsed_field="Interfaces",
        node_key=_interface_node_key,
        build_group_value=_build_interfaces_dict,
        row_noun="interface row(s)",
    ),
    "edges": CombinedQuestionSpec(
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
