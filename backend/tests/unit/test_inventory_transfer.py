"""Inventory export / import document format (Q3)."""

from __future__ import annotations

import pytest

from services.sources.nautobot.inventory_transfer import (
    build_export_document,
    parse_import_document,
)

_INVENTORY = {"id": 5, "name": "core", "scope": "global", "description": "d"}


def test_legacy_flat_conditions_become_a_tree() -> None:
    doc = build_export_document(
        {**_INVENTORY, "conditions": [{"field": "role", "operator": "equals", "value": "edge"}]},
        exported_by="alice",
    )
    assert doc["version"] == 2
    assert doc["metadata"]["exportedBy"] == "alice"
    assert doc["metadata"]["originalId"] == 5
    assert doc["conditionTree"]["type"] == "root"
    assert doc["conditionTree"]["items"] == [
        {"id": "item-0", "field": "role", "operator": "equals", "value": "edge"}
    ]


def test_v2_conditions_pass_the_tree_through() -> None:
    tree = {"type": "root", "items": []}
    doc = build_export_document(
        {**_INVENTORY, "conditions": [{"version": 2, "tree": tree}]}, exported_by="a"
    )
    assert doc["conditionTree"] is tree


def test_no_conditions_exports_null_tree() -> None:
    assert build_export_document({**_INVENTORY, "conditions": []}, exported_by="a")[
        "conditionTree"
    ] is None


def test_round_trip_import_payload() -> None:
    tree = {"type": "root", "items": [{"id": "x"}]}
    exported = build_export_document(
        {**_INVENTORY, "conditions": [{"version": 2, "tree": tree}]}, exported_by="a"
    )
    payload = parse_import_document(exported, created_by="bob")
    assert payload["name"] == "core (imported)"
    assert payload["conditions"] == [{"version": 2, "tree": tree}]
    assert payload["created_by"] == "bob"
    assert payload["scope"] == "global"


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"version": 1}, "Expected version 2"),
        ({"version": 2, "conditionTree": None}, "Missing condition tree"),
        ({"version": 2, "conditionTree": {"a": 1}, "metadata": {}}, "Missing metadata"),
    ],
)
def test_invalid_documents_raise(document: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_import_document(document, created_by="bob")
