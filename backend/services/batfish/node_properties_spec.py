"""The `nodeProperties` question spec, shared by the `batfish-node-properties`
workflow step (`workflow_steps.batfish_node_properties.executor`) and
`services.batfish.preview_service.BatfishPreviewService`'s ad-hoc "Batfish
Node Properties" preview.
"""

from __future__ import annotations

from services.batfish.facts_specs import PropertyQuestionSpec

NODE_PROPERTIES_SPEC = PropertyQuestionSpec(
    question_label="nodeProperties",
    node_key=lambda row: row.get("Node"),
    build_parsed_for_node=lambda rows: (
        {key: value for key, value in rows[-1].items() if key != "Node"} if rows else {}
    ),
    row_noun="node(s)",
)
