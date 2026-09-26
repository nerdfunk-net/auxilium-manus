"""Tests for scripts/ai_inventory_filter.py — the saved-conditions-to-canvas-
device_filter converter, see doc/ai_collaboration/AI_VOCABULARY.md's
inventory-targeting recipe. A Python port of the relevant slice of
frontend/.../inventory/utils/tree-format-converters.ts, verified against the
real dev DB (see PROCESS.md) by cross-checking it produces byte-identical
LogicalOperations to the existing runtime converter
(utils/inventory_converter.py::convert_saved_inventory_to_operations) for the
real LAB inventory."""

from __future__ import annotations

import unittest

from scripts.ai_inventory_filter import (
    condition_tree_to_filter_tree,
    saved_conditions_to_device_filter,
)


class SavedConditionsToDeviceFilterTests(unittest.TestCase):
    def test_flat_or_conditions_matches_lab_shape(self) -> None:
        conditions = [
            {
                "version": 2,
                "tree": {
                    "type": "root",
                    "internalLogic": "OR",
                    "items": [
                        {"id": "c1", "field": "name", "operator": "equals", "value": "LAB"},
                        {"id": "c2", "field": "name", "operator": "equals", "value": "lab-2"},
                    ],
                },
            }
        ]
        result = saved_conditions_to_device_filter(conditions)
        self.assertEqual(
            result,
            {
                "id": "root",
                "logic": "OR",
                "negate": False,
                "items": [
                    {"id": "c1", "field": "name", "operator": "equals", "value": "LAB"},
                    {"id": "c2", "field": "name", "operator": "equals", "value": "lab-2"},
                ],
            },
        )

    def test_empty_conditions_returns_empty_tree(self) -> None:
        self.assertEqual(
            saved_conditions_to_device_filter([]),
            {"id": "root", "logic": "AND", "negate": False, "items": []},
        )

    def test_wrong_version_returns_empty_tree(self) -> None:
        result = saved_conditions_to_device_filter([{"version": 1, "tree": {}}])
        self.assertEqual(result["items"], [])

    def test_not_a_list_returns_empty_tree(self) -> None:
        result = saved_conditions_to_device_filter({"tree": {}})
        self.assertEqual(result["items"], [])

    def test_missing_tree_type_root_returns_empty_tree(self) -> None:
        result = saved_conditions_to_device_filter([{"version": 2, "tree": {"items": []}}])
        self.assertEqual(result["items"], [])

    def test_single_top_level_not_group_unwraps_to_negate(self) -> None:
        tree = {
            "type": "root",
            "internalLogic": "AND",
            "items": [
                {
                    "id": "g1",
                    "type": "group",
                    "logic": "NOT",
                    "internalLogic": "OR",
                    "items": [
                        {"id": "c1", "field": "role", "operator": "equals", "value": "switch"}
                    ],
                }
            ],
        }
        result = condition_tree_to_filter_tree(tree)
        self.assertEqual(
            result,
            {
                "id": "root",
                "logic": "OR",
                "negate": True,
                "items": [{"id": "c1", "field": "role", "operator": "equals", "value": "switch"}],
            },
        )

    def test_nested_non_not_group_is_preserved_as_a_child(self) -> None:
        tree = {
            "type": "root",
            "internalLogic": "AND",
            "items": [
                {"id": "c1", "field": "role", "operator": "equals", "value": "router"},
                {
                    "id": "g1",
                    "type": "group",
                    "logic": "AND",
                    "internalLogic": "OR",
                    "items": [
                        {"id": "c2", "field": "location", "operator": "equals", "value": "NYC"},
                        {"id": "c3", "field": "location", "operator": "equals", "value": "LA"},
                    ],
                },
            ],
        }
        result = condition_tree_to_filter_tree(tree)
        self.assertEqual(
            result,
            {
                "id": "root",
                "logic": "AND",
                "negate": False,
                "items": [
                    {"id": "c1", "field": "role", "operator": "equals", "value": "router"},
                    {
                        "id": "g1",
                        "logic": "OR",
                        "negate": False,
                        "items": [
                            {"id": "c2", "field": "location", "operator": "equals", "value": "NYC"},
                            {"id": "c3", "field": "location", "operator": "equals", "value": "LA"},
                        ],
                    },
                ],
            },
        )

    def test_two_not_groups_is_not_the_single_child_special_case(self) -> None:
        # The NOT-unwrap special case only applies when the NOT group is the
        # tree's ONE AND ONLY item — two items (even if both are NOT groups)
        # must fall through to the plain root_group path unchanged.
        tree = {
            "type": "root",
            "internalLogic": "AND",
            "items": [
                {
                    "id": "g1",
                    "type": "group",
                    "logic": "NOT",
                    "internalLogic": "OR",
                    "items": [{"id": "c1", "field": "role", "operator": "equals", "value": "a"}],
                },
                {
                    "id": "g2",
                    "type": "group",
                    "logic": "NOT",
                    "internalLogic": "OR",
                    "items": [{"id": "c2", "field": "role", "operator": "equals", "value": "b"}],
                },
            ],
        }
        result = condition_tree_to_filter_tree(tree)
        self.assertEqual(result["negate"], False)
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["items"][0]["negate"])
        self.assertTrue(result["items"][1]["negate"])


class RealLabInventoryRegressionTest(unittest.TestCase):
    """Loads the real LAB inventory from the dev DB (not a fixture) and
    cross-checks the converted device_filter produces byte-identical
    LogicalOperations to the existing, known-correct runtime converter for
    the same inventory. Skips gracefully if the dev DB/LAB inventory isn't
    reachable (e.g. CI without a live Postgres)."""

    def test_matches_runtime_converter_for_real_lab_inventory(self) -> None:
        try:
            from core.database import SessionLocal
            from repositories.inventory_repository import InventoryRepository
            from services.sources.nautobot.persistence_service import InventoryService
            from utils.inventory_converter import convert_saved_inventory_to_operations
            from workflow_steps.get_nautobot_devices.executor import _filter_tree_to_operations

            with SessionLocal() as db:
                inventory = InventoryService(InventoryRepository(db)).get_inventory_by_name(
                    "LAB", "admin"
                )
        except Exception as exc:  # pragma: no cover - environment-dependent
            self.skipTest(f"dev DB / LAB inventory not reachable: {exc}")
            return

        if inventory is None:
            self.skipTest("LAB inventory not present in this DB")
            return

        expected = convert_saved_inventory_to_operations(inventory["conditions"])
        device_filter = saved_conditions_to_device_filter(inventory["conditions"])
        actual = _filter_tree_to_operations(device_filter)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
