"""The `interfaceProperties` question spec, shared by the
`batfish-interface-properties` workflow step
(`workflow_steps.batfish_interface_properties.executor`) and
`services.batfish.preview_service.BatfishPreviewService`'s ad-hoc "Batfish
Interface Properties" preview.

A different, interface-scoped question from nodeProperties -- one row per
(node, interface) pair, keyed by an `Interface` column that serializes to a
nested `{"hostname": ..., "interface": ...}` dict, not a plain string (see
doc/BATFISH_INTEGRATION.md "Batfish Interface Properties"). Each node's
payload nests under "Interfaces" rather than flat -- the one real difference
from nodeProperties.
"""

from __future__ import annotations

from typing import Any

from services.batfish.facts_specs import PropertyQuestionSpec


def _interface_node_key(row: dict[str, Any]) -> str | None:
    interface = row.get("Interface")
    return interface.get("hostname") if isinstance(interface, dict) else None


def _build_interfaces_parsed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every matching interface's own fields for one node, nested the same
    way `pybatfish.client._facts.get_facts()` nests this question's results."""
    interfaces: dict[str, dict[str, Any]] = {}
    for row in rows:
        interface = row.get("Interface")
        name = interface.get("interface") if isinstance(interface, dict) else None
        if not name:
            continue
        interfaces[str(name)] = {key: value for key, value in row.items() if key != "Interface"}
    return {"Interfaces": interfaces}


INTERFACE_PROPERTIES_SPEC = PropertyQuestionSpec(
    question_label="interfaceProperties",
    node_key=_interface_node_key,
    build_parsed_for_node=_build_interfaces_parsed,
    row_noun="interface(s)",
)
