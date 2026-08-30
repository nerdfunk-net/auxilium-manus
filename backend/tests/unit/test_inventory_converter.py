"""Table-driven tests for utils/inventory_converter.py."""

from __future__ import annotations

import unittest

from utils.inventory_converter import (
    convert_saved_inventory_to_operations,
    tree_to_operations,
)


def _cond(field: str, value: str, operator: str = "equals") -> dict:
    return {"field": field, "operator": operator, "value": value}


class TreeToOperationsTests(unittest.TestCase):
    def test_invalid_tree_returns_empty(self) -> None:
        self.assertEqual(tree_to_operations(None), [])
        self.assertEqual(tree_to_operations("nope"), [])
        self.assertEqual(tree_to_operations({"items": []}), [])

    def test_single_condition_tree(self) -> None:
        ops = tree_to_operations(
            {"internalLogic": "AND", "items": [_cond("location", "NYC")]}
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].conditions[0].field, "location")

    def test_multiple_root_conditions_merge_into_one_operation(self) -> None:
        ops = tree_to_operations(
            {
                "internalLogic": "OR",
                "items": [_cond("role", "leaf"), _cond("status", "active")],
            }
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].operation_type, "OR")
        self.assertEqual({c.field for c in ops[0].conditions}, {"role", "status"})

    def test_group_becomes_nested_operation(self) -> None:
        tree = {
            "internalLogic": "AND",
            "items": [
                _cond("status", "active"),
                {
                    "type": "group",
                    "logic": "AND",
                    "internalLogic": "OR",
                    "items": [_cond("role", "leaf"), _cond("role", "spine")],
                },
            ],
        }
        ops = tree_to_operations(tree)
        self.assertEqual(len(ops), 1)
        self.assertEqual(len(ops[0].nested_operations), 1)
        self.assertEqual(ops[0].nested_operations[0].operation_type, "OR")

    def test_not_group_is_separate_operation(self) -> None:
        tree = {
            "internalLogic": "AND",
            "items": [
                _cond("status", "active"),
                {
                    "type": "group",
                    "logic": "NOT",
                    "internalLogic": "AND",
                    "items": [_cond("role", "mgmt")],
                },
            ],
        }
        ops = tree_to_operations(tree)
        self.assertEqual([o.operation_type for o in ops], ["AND", "NOT"])

    def test_nested_not_subgroup_marked(self) -> None:
        tree = {
            "internalLogic": "AND",
            "items": [
                {
                    "type": "group",
                    "logic": "AND",
                    "internalLogic": "AND",
                    "items": [
                        _cond("status", "active"),
                        {
                            "type": "group",
                            "logic": "NOT",
                            "internalLogic": "AND",
                            "items": [_cond("role", "x")],
                        },
                    ],
                },
                _cond("location", "dc"),
            ],
        }
        ops = tree_to_operations(tree)
        nested = ops[0].nested_operations[0]
        self.assertEqual(nested.nested_operations[0].operation_type, "NOT")


class ConvertSavedInventoryTests(unittest.TestCase):
    def test_empty_conditions(self) -> None:
        self.assertEqual(convert_saved_inventory_to_operations([]), [])

    def test_non_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            convert_saved_inventory_to_operations({"version": 2})

    def test_non_dict_first_item_raises(self) -> None:
        with self.assertRaises(ValueError):
            convert_saved_inventory_to_operations(["nope"])

    def test_unsupported_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            convert_saved_inventory_to_operations([{"version": 1, "tree": {}}])

    def test_missing_tree_raises(self) -> None:
        with self.assertRaises(ValueError):
            convert_saved_inventory_to_operations([{"version": 2}])

    def test_version_2_tree_converts(self) -> None:
        ops = convert_saved_inventory_to_operations(
            [{"version": 2, "tree": {"internalLogic": "AND", "items": [_cond("role", "leaf")]}}]
        )
        self.assertEqual(ops[0].conditions[0].value, "leaf")


if __name__ == "__main__":
    unittest.main()
