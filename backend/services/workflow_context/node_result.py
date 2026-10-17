"""Namespacing for a step's own node-scoped entry in ``DeviceContext.parsed``.

Steps that stash their own per-run result (not a user-chosen ``output_key``
namespace — those are already fine, since ``parse_output_key`` forbids dots)
nest it under their own canvas node id: ``parsed[node_id][key]``. That keeps
it a real, dot-path-addressable location (``parsed.<node_id>.<key>.<field>``)
that ``services.workflow_context.attribute_path`` and the attribute-path
picker (``attribute_path_discovery.py``) can walk like any other nested dict,
instead of a flat ``"<node_id>.<key>"`` string key that the shared dot-path
resolver can never split back apart (it treats every ``.`` as a path
separator, so it can't distinguish a literal dot inside a key from one that
separates segments).
"""

from __future__ import annotations

from typing import Any


def set_node_result(parsed: dict[str, Any], node_id: str, key: str, value: Any) -> dict[str, Any]:
    """Return a new ``parsed`` dict with ``parsed[node_id][key] = value``."""
    updated = dict(parsed)
    node_bag = dict(updated.get(node_id) or {})
    node_bag[key] = value
    updated[node_id] = node_bag
    return updated


def get_node_result(parsed: dict[str, Any], node_id: str, key: str) -> Any:
    """Read ``parsed[node_id][key]``, or ``None`` if either level is absent."""
    node_bag = parsed.get(node_id)
    if not isinstance(node_bag, dict):
        return None
    return node_bag.get(key)
