"""Inventory export / import document format (version 2). Pure functions, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

EXPORT_VERSION = 2


def build_export_document(inventory: dict[str, Any], *, exported_by: str) -> dict[str, Any]:
    tree: Any = None
    conditions = inventory.get("conditions", [])
    if conditions:
        first = conditions[0]
        if isinstance(first, dict) and first.get("version") == EXPORT_VERSION:
            tree = first.get("tree")
        else:
            tree = {
                "type": "root",
                "internalLogic": "AND",
                "items": [
                    {
                        "id": f"item-{index}",
                        "field": cond.get("field", ""),
                        "operator": cond.get("operator", ""),
                        "value": cond.get("value", ""),
                    }
                    for index, cond in enumerate(conditions)
                ],
            }
    return {
        "version": EXPORT_VERSION,
        "metadata": {
            "name": inventory["name"],
            "description": inventory.get("description", ""),
            "scope": inventory["scope"],
            "exportedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "exportedBy": exported_by,
            "originalId": inventory["id"],
        },
        "conditionTree": tree,
    }


def parse_import_document(document: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Validate an exported document and return the ``create_inventory`` payload.

    Raises ``ValueError`` (→ HTTP 400) with the messages the router used before.
    """
    if document.get("version") != EXPORT_VERSION:
        raise ValueError("Invalid inventory file format. Expected version 2.")
    if not document.get("conditionTree"):
        raise ValueError("Invalid inventory file. Missing condition tree.")
    metadata = document.get("metadata") or {}
    if not metadata.get("name"):
        raise ValueError("Invalid inventory file. Missing metadata.")
    return {
        "name": f"{metadata['name']} (imported)",
        "description": metadata.get("description", "Imported inventory"),
        "conditions": [{"version": EXPORT_VERSION, "tree": document["conditionTree"]}],
        "template_category": None,
        "template_name": None,
        "scope": "global",
        "created_by": created_by,
    }
