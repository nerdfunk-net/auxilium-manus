"""Tests for field type/sample inference used by the dataset catalog."""

from __future__ import annotations

import unittest

from services.reports.field_stats import MAX_SAMPLE_VALUES, infer_fields


class InferFieldsTests(unittest.TestCase):
    def test_types_per_field(self) -> None:
        rows = [
            {"serial": "A", "ports": 48, "stacked": True, "ratio": 0.5},
            {"serial": "B", "ports": 24, "stacked": False, "ratio": 1},
        ]
        fields = {f.name: f for f in infer_fields(rows, ["serial", "ports", "stacked", "ratio"])}

        self.assertEqual(fields["serial"].type, "string")
        self.assertEqual(fields["ports"].type, "number")
        self.assertEqual(fields["stacked"].type, "boolean")
        self.assertEqual(fields["ratio"].type, "number")

    def test_bool_is_not_a_number(self) -> None:
        (field,) = infer_fields([{"x": True}, {"x": 3}], ["x"])
        self.assertEqual(field.type, "mixed")

    def test_mixed_and_unknown(self) -> None:
        mixed, unknown = infer_fields([{"a": 1, "b": None}, {"a": "x", "b": None}], ["a", "b"])
        self.assertEqual(mixed.type, "mixed")
        self.assertEqual(unknown.type, "unknown")

    def test_null_share_counts_missing_keys(self) -> None:
        (field,) = infer_fields([{"a": 1}, {"a": None}, {}, {"a": 2}], ["a"])
        self.assertEqual(field.null_share, 0.5)

    def test_sample_values_are_distinct_first_seen_and_truncated(self) -> None:
        rows = [{"a": v} for v in ["x", "y", "x", "z" * 300, "w", "v", "u"]]
        (field,) = infer_fields(rows, ["a"])

        self.assertEqual(len(field.sample_values), MAX_SAMPLE_VALUES)
        self.assertEqual(field.sample_values[:2], ["x", "y"])
        self.assertTrue(all(len(v) <= 100 for v in field.sample_values))

    def test_declared_order_first_then_extra_keys(self) -> None:
        fields = infer_fields([{"b": 1, "a": 2, "z": 3}], ["a", "b"])
        self.assertEqual([f.name for f in fields], ["a", "b", "z"])

    def test_no_rows_gives_unknown_fields(self) -> None:
        (field,) = infer_fields([], ["a"])
        self.assertEqual((field.type, field.null_share, field.sample_values), ("unknown", 0.0, []))
