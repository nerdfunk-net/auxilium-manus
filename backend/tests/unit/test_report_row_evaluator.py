"""The in-memory evaluator of ``ReportQuery`` (sources that are not SQL tables)."""

from __future__ import annotations

import unittest
from typing import Any

from models.reports import DatasetInfo, FieldInfo, ReportQuery
from services.reports.errors import ReportQueryError
from services.reports.sources.row_evaluator import evaluate, validate


def _field(name: str, kind: str) -> FieldInfo:
    return FieldInfo(name=name, type=kind, null_share=0.0, sample_values=[])  # type: ignore[arg-type]


DATASET = DatasetInfo(
    name="devices",
    mode="device",
    fields=[
        _field("location", "string"),
        _field("device_type", "string"),
        _field("serial", "string"),
        _field("ports", "number"),
        _field("managed", "boolean"),
    ],
)

ROWS: list[dict[str, Any]] = [
    {
        "device_name": "sw1",
        "location": "Berlin",
        "device_type": "C9300",
        "serial": "S1",
        "ports": 48,
        "managed": True,
    },
    {
        "device_name": "sw2",
        "location": "Berlin",
        "device_type": "C9300",
        "serial": None,
        "ports": 24,
        "managed": True,
    },
    {
        "device_name": "rt1",
        "location": "Munich",
        "device_type": "ISR4331",
        "serial": "S3",
        "ports": 4,
        "managed": False,
    },
    {
        "device_name": "rt2",
        "location": None,
        "device_type": "ISR4331",
        "serial": "S4",
        "ports": None,
        "managed": None,
    },
]


def run(**spec: Any):
    query = ReportQuery(source="nautobot", dataset="devices", **spec)
    return evaluate(query, DATASET, ROWS)


class ListModeTests(unittest.TestCase):
    def test_default_columns_are_device_name_then_fields_ordered_by_name(self) -> None:
        result = run()
        self.assertEqual(
            [c.key for c in result.columns],
            ["device_name", "location", "device_type", "serial", "ports", "managed"],
        )
        self.assertEqual([r[0] for r in result.rows], ["rt1", "rt2", "sw1", "sw2"])

    def test_select_picks_columns(self) -> None:
        result = run(select=["device_name", "serial"])
        self.assertEqual(result.rows[0], ["rt1", "S3"])

    def test_limit_marks_truncated(self) -> None:
        result = run(select=["device_name"], limit=3)
        self.assertEqual(len(result.rows), 3)
        self.assertTrue(result.truncated)

    def test_missing_values_sort_like_postgresql(self) -> None:
        """Ascending puts them last, descending first (the SQL compiler's database)."""
        asc = run(select=["device_name", "serial"], order_by=[{"key": "serial"}])
        desc = run(
            select=["device_name", "serial"],
            order_by=[{"key": "serial", "direction": "desc"}],
        )
        self.assertEqual([r[1] for r in asc.rows], ["S1", "S3", "S4", None])
        self.assertEqual([r[1] for r in desc.rows], [None, "S4", "S3", "S1"])


class FilterTests(unittest.TestCase):
    def names(self, *filters: dict[str, Any]) -> list[str]:
        return [r[0] for r in run(select=["device_name"], filters=list(filters)).rows]

    def test_eq_and_ne(self) -> None:
        self.assertEqual(
            self.names({"field": "location", "op": "eq", "value": "Berlin"}), ["sw1", "sw2"]
        )
        # ne also matches a missing value, like the SQL compiler.
        self.assertEqual(
            self.names({"field": "location", "op": "ne", "value": "Berlin"}), ["rt1", "rt2"]
        )

    def test_in_contains_is_null(self) -> None:
        self.assertEqual(
            self.names({"field": "device_type", "op": "in", "value": ["ISR4331"]}), ["rt1", "rt2"]
        )
        self.assertEqual(
            self.names({"field": "device_type", "op": "contains", "value": "c93"}), ["sw1", "sw2"]
        )
        self.assertEqual(self.names({"field": "serial", "op": "is_null"}), ["sw2"])
        self.assertEqual(len(self.names({"field": "serial", "op": "not_null"})), 3)

    def test_numeric_comparison(self) -> None:
        self.assertEqual(self.names({"field": "ports", "op": "gte", "value": 24}), ["sw1", "sw2"])

    def test_bad_operator_for_type_is_rejected(self) -> None:
        with self.assertRaises(ReportQueryError):
            self.names({"field": "location", "op": "gt", "value": 1})
        with self.assertRaises(ReportQueryError):
            self.names({"field": "ports", "op": "contains", "value": "4"})
        with self.assertRaises(ReportQueryError):
            self.names({"field": "ports", "op": "eq", "value": "48"})

    def test_unknown_and_time_fields_are_rejected(self) -> None:
        with self.assertRaises(ReportQueryError):
            self.names({"field": "nope", "op": "eq", "value": "x"})
        with self.assertRaises(ReportQueryError):
            self.names({"field": "collected_at", "op": "is_null"})


class SummaryTests(unittest.TestCase):
    def test_group_by_with_count_orders_by_group_nulls_last(self) -> None:
        result = run(group_by=["location"], metrics=[{"op": "count", "alias": "devices"}])
        self.assertEqual(result.rows, [["Berlin", 2], ["Munich", 1], [None, 1]])
        self.assertEqual([c.key for c in result.columns], ["location", "devices"])

    def test_metrics(self) -> None:
        result = run(
            metrics=[
                {"op": "count", "field": "serial", "alias": "with_serial"},
                {"op": "count_missing", "field": "serial", "alias": "no_serial"},
                {"op": "count_distinct", "field": "device_type", "alias": "types"},
                {"op": "sum", "field": "ports", "alias": "total"},
                {"op": "avg", "field": "ports", "alias": "mean"},
                {"op": "min", "field": "serial", "alias": "first"},
                {"op": "max", "field": "ports", "alias": "most"},
                {"op": "count_devices", "alias": "devs"},
                {"op": "count_items", "alias": "items"},
            ]
        )
        self.assertEqual(result.rows, [[3, 1, 2, 76, 76 / 3, "S1", 48, 4, 4]])

    def test_summary_without_rows_still_returns_one_row(self) -> None:
        result = run(
            filters=[{"field": "location", "op": "eq", "value": "Nowhere"}],
            metrics=[{"op": "count", "alias": "n"}, {"op": "sum", "field": "ports", "alias": "s"}],
        )
        self.assertEqual(result.rows, [[0, None]])

    def test_order_by_metric_desc(self) -> None:
        result = run(
            group_by=["device_type"],
            metrics=[{"op": "count", "alias": "n"}],
            order_by=[{"key": "n", "direction": "desc"}, {"key": "device_type"}],
        )
        self.assertEqual(result.rows, [["C9300", 2], ["ISR4331", 2]])

    def test_group_by_needs_metric_and_select_excludes_metrics(self) -> None:
        with self.assertRaises(ReportQueryError):
            run(group_by=["location"])
        with self.assertRaises(ReportQueryError):
            run(select=["serial"], metrics=[{"op": "count"}])

    def test_sum_needs_number_and_duplicate_columns_are_rejected(self) -> None:
        with self.assertRaises(ReportQueryError):
            run(metrics=[{"op": "sum", "field": "serial"}])
        with self.assertRaises(ReportQueryError):
            run(metrics=[{"op": "count"}, {"op": "count"}])

    def test_history_scope_is_rejected(self) -> None:
        with self.assertRaises(ReportQueryError):
            run(scope={"kind": "history"})

    def test_order_by_must_name_an_output_column(self) -> None:
        with self.assertRaises(ReportQueryError):
            run(select=["serial"], order_by=[{"key": "ports"}])


class ValidateTests(unittest.TestCase):
    def test_validate_does_not_need_rows(self) -> None:
        validate(ReportQuery(source="nautobot", dataset="devices", select=["serial"]), DATASET)
        with self.assertRaises(ReportQueryError):
            validate(ReportQuery(source="nautobot", dataset="devices", select=["nope"]), DATASET)


if __name__ == "__main__":
    unittest.main()
