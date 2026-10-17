"""Tests for the report query compiler, run against in-memory SQLite with real rows."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from models.reports import DatasetInfo, FieldInfo, QueryResult, ReportQuery
from services.reports.errors import ReportQueryError
from services.reports.query_compiler import compile_query, execute_query

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def _field(name: str, kind: str) -> FieldInfo:
    return FieldInfo(name=name, type=kind, null_share=0.0, sample_values=[])  # type: ignore[arg-type]


INVENTORY = DatasetInfo(
    name="inventory",
    mode="device",
    fields=[
        _field("serial", "string"),
        _field("location", "string"),
        _field("ports", "number"),
        _field("stacked", "boolean"),
        _field("misc", "mixed"),
    ],
)
IFACES = DatasetInfo(
    name="ifaces", mode="items", fields=[_field("name", "string"), _field("status", "string")]
)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[ReportDataRecord.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self._collection = 0

    def add(self, device: str, dataset: str, rows: list[dict], *, at: datetime = NOW) -> None:
        self._collection += 1
        for position, data in enumerate(rows or [{}]):
            self.db.add(
                ReportDataRecord(
                    device_name=device,
                    dataset=dataset,
                    data=data,
                    collection_id=f"c{self._collection}",
                    position=position,
                    is_empty=not rows,
                    created_at=at,
                )
            )
        self.db.commit()

    def run_query(self, dataset: DatasetInfo = INVENTORY, **query: Any) -> QueryResult:
        spec = ReportQuery.model_validate({"dataset": dataset.name, **query})
        return execute_query(self.db, spec, dataset)

    def seed_inventory(self) -> None:
        self.add(
            "sw1", "inventory", [{"serial": "A1", "location": "dc1", "ports": 48, "stacked": True}]
        )
        self.add(
            "sw2", "inventory", [{"serial": "B2", "location": "dc1", "ports": 24, "stacked": False}]
        )
        self.add(
            "sw3", "inventory", [{"serial": "C3", "location": "dc2", "ports": 48, "stacked": None}]
        )
        self.add("sw4", "inventory", [{"serial": None, "location": "dc2", "ports": None}])


class ListModeTests(_Base):
    def test_default_lists_device_and_all_fields_newest_collection_only(self) -> None:
        self.add("sw1", "inventory", [{"serial": "OLD"}], at=NOW - timedelta(days=1))
        self.add("sw1", "inventory", [{"serial": "NEW", "location": "dc1"}])

        result = self.run_query()

        self.assertEqual(
            [c.key for c in result.columns],
            ["device_name", "serial", "location", "ports", "stacked", "misc"],
        )
        self.assertEqual(result.rows, [["sw1", "NEW", "dc1", None, None, None]])

    def test_select_order_and_limit_with_truncation(self) -> None:
        self.seed_inventory()

        result = self.run_query(
            select=["device_name", "serial"],
            order_by=[{"key": "device_name", "direction": "desc"}],
            limit=3,
        )

        self.assertEqual([r[0] for r in result.rows], ["sw4", "sw3", "sw2"])
        self.assertTrue(result.truncated)
        self.assertFalse(self.run_query(limit=10).truncated)

    def test_item_dataset_returns_one_row_per_item(self) -> None:
        self.add(
            "sw1", "ifaces", [{"name": "Gi1", "status": "up"}, {"name": "Gi2", "status": "down"}]
        )
        self.add("sw2", "ifaces", [])  # marker: no items

        result = self.run_query(IFACES, select=["device_name", "name"])

        self.assertEqual(result.rows, [["sw1", "Gi1"], ["sw1", "Gi2"]])


class FilterTests(_Base):
    def devices(self, **query: Any) -> list[str]:
        return [r[0] for r in self.run_query(select=["device_name"], **query).rows]

    def setUp(self) -> None:
        super().setUp()
        self.seed_inventory()

    def test_eq_and_ne_string(self) -> None:
        self.assertEqual(
            self.devices(filters=[{"field": "location", "op": "eq", "value": "dc1"}]),
            ["sw1", "sw2"],
        )
        # ne keeps rows where the field is missing too.
        self.assertEqual(
            self.devices(filters=[{"field": "serial", "op": "ne", "value": "A1"}]),
            ["sw2", "sw3", "sw4"],
        )

    def test_numeric_comparisons(self) -> None:
        self.assertEqual(
            self.devices(filters=[{"field": "ports", "op": "gt", "value": 24}]), ["sw1", "sw3"]
        )
        self.assertEqual(
            self.devices(filters=[{"field": "ports", "op": "lte", "value": 24}]), ["sw2"]
        )
        self.assertEqual(
            self.devices(filters=[{"field": "ports", "op": "eq", "value": 48}]), ["sw1", "sw3"]
        )

    def test_boolean_eq(self) -> None:
        self.assertEqual(
            self.devices(filters=[{"field": "stacked", "op": "eq", "value": True}]), ["sw1"]
        )

    def test_in_and_device_name(self) -> None:
        self.assertEqual(
            self.devices(filters=[{"field": "device_name", "op": "in", "value": ["sw2", "sw4"]}]),
            ["sw2", "sw4"],
        )

    def test_contains_is_case_insensitive_and_escapes_wildcards(self) -> None:
        self.add("sw5", "inventory", [{"serial": "50%_off"}])
        self.assertEqual(
            self.devices(filters=[{"field": "serial", "op": "contains", "value": "a1"}]), ["sw1"]
        )
        self.assertEqual(
            self.devices(filters=[{"field": "serial", "op": "contains", "value": "%_"}]), ["sw5"]
        )

    def test_null_filters(self) -> None:
        self.assertEqual(self.devices(filters=[{"field": "serial", "op": "is_null"}]), ["sw4"])
        self.assertEqual(
            self.devices(filters=[{"field": "ports", "op": "not_null"}]), ["sw1", "sw2", "sw3"]
        )

    def test_mixed_field_compares_the_json_value(self) -> None:
        # (A boolean inside a mixed field is covered on PostgreSQL: SQLite extracts JSON true as 1.)
        self.add("sw6", "inventory", [{"misc": 10}])
        self.add("sw7", "inventory", [{"misc": "10"}])
        self.assertEqual(
            self.devices(filters=[{"field": "misc", "op": "eq", "value": 10}]), ["sw6"]
        )
        self.assertEqual(
            self.devices(filters=[{"field": "misc", "op": "eq", "value": "10"}]), ["sw7"]
        )

    def test_filters_are_anded(self) -> None:
        got = self.devices(
            filters=[
                {"field": "location", "op": "eq", "value": "dc2"},
                {"field": "ports", "op": "gte", "value": 48},
            ]
        )
        self.assertEqual(got, ["sw3"])


class AggregateTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.seed_inventory()

    def test_count_all(self) -> None:
        result = self.run_query(metrics=[{"op": "count"}])
        self.assertEqual([c.key for c in result.columns], ["count"])
        self.assertEqual(result.rows, [[4]])

    def test_group_by_with_count_sorted(self) -> None:
        result = self.run_query(
            group_by=["location"],
            metrics=[{"op": "count", "alias": "devices"}],
            order_by=[{"key": "devices", "direction": "desc"}, {"key": "location"}],
        )
        self.assertEqual(result.rows, [["dc1", 2], ["dc2", 2]])

    def test_numeric_metrics(self) -> None:
        result = self.run_query(
            metrics=[
                {"op": "sum", "field": "ports"},
                {"op": "avg", "field": "ports"},
                {"op": "min", "field": "ports"},
                {"op": "max", "field": "ports"},
            ]
        )
        self.assertEqual(result.rows, [[120.0, 40.0, 24.0, 48.0]])

    def test_distinct_and_missing(self) -> None:
        result = self.run_query(
            metrics=[
                {"op": "count_distinct", "field": "location"},
                {"op": "count_missing", "field": "serial"},
                {"op": "count_distinct", "field": "device_name"},
            ]
        )
        self.assertEqual(result.rows, [[2, 1, 4]])

    def test_group_by_default_order_is_the_group_columns(self) -> None:
        result = self.run_query(group_by=["location"], metrics=[{"op": "count"}])
        self.assertEqual([r[0] for r in result.rows], ["dc1", "dc2"])

    def test_filter_then_count_shutdown_interfaces_per_device(self) -> None:
        self.add(
            "sw1",
            "ifaces",
            [{"name": "Gi1", "status": "up"}, {"name": "Gi2", "status": "disabled"}],
        )
        self.add(
            "sw2",
            "ifaces",
            [{"name": "Gi1", "status": "disabled"}, {"name": "Gi2", "status": "disabled"}],
        )

        result = self.run_query(
            IFACES,
            filters=[{"field": "status", "op": "eq", "value": "disabled"}],
            group_by=["device_name"],
            metrics=[{"op": "count", "alias": "shutdown"}],
        )

        self.assertEqual(result.rows, [["sw1", 1], ["sw2", 2]])


class HistoryTests(_Base):
    def test_history_includes_older_collections(self) -> None:
        self.add("sw1", "inventory", [{"ports": 1}], at=NOW - timedelta(days=2))
        self.add("sw1", "inventory", [{"ports": 2}])

        latest = self.run_query(select=["ports"])
        history = self.run_query(select=["ports"], scope={"kind": "history"})

        self.assertEqual(latest.rows, [[2]])
        self.assertEqual(history.rows, [[1], [2]])

    def test_since_and_until(self) -> None:
        for days in (3, 2, 1, 0):
            self.add("sw1", "inventory", [{"ports": days}], at=NOW - timedelta(days=days))

        result = self.run_query(
            select=["ports"],
            scope={
                "kind": "history",
                "since": (NOW - timedelta(days=2, hours=1)).isoformat(),
                "until": (NOW - timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(sorted(r[0] for r in result.rows), [1, 2])

    def test_markers_never_appear_in_history(self) -> None:
        self.add("sw1", "ifaces", [])
        self.assertEqual(self.run_query(IFACES, scope={"kind": "history"}).rows, [])

    def test_day_bucket_trend(self) -> None:
        for days, ports in ((2, 10), (2, 20), (1, 30)):
            self.add(
                f"sw{days}{ports}", "inventory", [{"ports": ports}], at=NOW - timedelta(days=days)
            )

        result = self.run_query(
            scope={"kind": "history", "bucket": "day"},
            group_by=["time_bucket"],
            metrics=[{"op": "avg", "field": "ports", "alias": "avg_ports"}],
        )

        self.assertEqual([r[1] for r in result.rows], [15.0, 30.0])
        self.assertEqual(result.columns[0].type, "datetime")

    def test_week_bucket_groups_a_week_together(self) -> None:
        self.add("a", "inventory", [{"ports": 1}], at=datetime(2026, 1, 5, tzinfo=UTC))  # Monday
        self.add("b", "inventory", [{"ports": 1}], at=datetime(2026, 1, 11, tzinfo=UTC))  # Sunday
        self.add(
            "c", "inventory", [{"ports": 1}], at=datetime(2026, 1, 12, tzinfo=UTC)
        )  # next Monday

        result = self.run_query(
            scope={"kind": "history", "bucket": "week"},
            group_by=["time_bucket"],
            metrics=[{"op": "count"}],
        )
        self.assertEqual([r[1] for r in result.rows], [2, 1])


class ValueHardeningTests(_Base):
    def test_filter_values_must_be_finite_and_in_range(self) -> None:
        for value in (float("nan"), float("inf"), 10**400, -(10**30)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ReportQuery.model_validate(
                    {
                        "dataset": "inventory",
                        "filters": [{"field": "ports", "op": "eq", "value": value}],
                    }
                )
        with self.assertRaises(ValueError):
            ReportQuery.model_validate(
                {
                    "dataset": "inventory",
                    "filters": [{"field": "misc", "op": "in", "value": [1, None]}],
                }
            )

    def test_legacy_reserved_keys_do_not_break_the_default_list_query(self) -> None:
        from services.reports.field_stats import infer_fields

        fields = infer_fields([{"serial": "A", "device_name": "legacy"}], ["serial"])

        self.assertEqual([f.name for f in fields], ["serial"])


class ValidationTests(_Base):
    def assertInvalid(self, message: str, dataset: DatasetInfo = INVENTORY, **query: Any) -> None:
        with self.assertRaisesRegex(ReportQueryError, message):
            self.run_query(dataset, **query)

    def test_unknown_names(self) -> None:
        self.assertInvalid("unknown field", select=["nope"])
        self.assertInvalid("unknown field", filters=[{"field": "nope", "op": "is_null"}])
        self.assertInvalid("unknown field", metrics=[{"op": "sum", "field": "nope"}])
        self.assertInvalid("unknown field", group_by=["nope"], metrics=[{"op": "count"}])

    def test_numeric_ops_need_numbers(self) -> None:
        self.assertInvalid("number", metrics=[{"op": "sum", "field": "serial"}])
        self.assertInvalid("number", filters=[{"field": "serial", "op": "gt", "value": 1}])
        self.assertInvalid("number", filters=[{"field": "misc", "op": "gt", "value": 1}])

    def test_value_types_are_checked(self) -> None:
        self.assertInvalid("number", filters=[{"field": "ports", "op": "eq", "value": "many"}])
        self.assertInvalid("boolean", filters=[{"field": "stacked", "op": "eq", "value": "yes"}])
        self.assertInvalid("contains", filters=[{"field": "ports", "op": "contains", "value": "4"}])

    def test_group_by_needs_metrics_and_select_excludes_metrics(self) -> None:
        self.assertInvalid("metric", group_by=["location"])
        self.assertInvalid("select", select=["serial"], metrics=[{"op": "count"}])

    def test_time_bucket_needs_a_bucketed_history_scope(self) -> None:
        self.assertInvalid("time_bucket", group_by=["time_bucket"], metrics=[{"op": "count"}])

    def test_order_by_must_name_an_output_column(self) -> None:
        self.assertInvalid("order", select=["serial"], order_by=[{"key": "location"}])

    def test_duplicate_output_keys_need_an_alias(self) -> None:
        self.assertInvalid("alias", metrics=[{"op": "count"}, {"op": "count"}])

    def test_reserved_pseudo_fields_in_dataset_metadata_are_not_special(self) -> None:
        # device_name is always the device, never a JSON key.
        self.add("sw1", "inventory", [{"serial": "A"}])
        self.assertEqual(self.run_query(select=["device_name"]).rows, [["sw1"]])

    def test_compile_exposes_column_types(self) -> None:
        compiled = compile_query(
            ReportQuery.model_validate(
                {
                    "dataset": "inventory",
                    "group_by": ["location"],
                    "metrics": [{"op": "sum", "field": "ports"}],
                }
            ),
            INVENTORY,
            dialect="sqlite",
        )
        self.assertEqual(
            [(c.key, c.type) for c in compiled.columns],
            [("location", "string"), ("sum_ports", "number")],
        )


class DeviceLevelMetricTests(_Base):
    """count_devices / count_items see empty-collection markers, so zero is visible."""

    def seed(self) -> None:
        self.add("sw1", "ifaces", [{"name": "a", "status": "up"}, {"name": "b", "status": "down"}])
        self.add("sw2", "ifaces", [])  # collected, found nothing
        self.add("sw3", "ifaces", [{"name": "c", "status": "up"}])

    def test_count_devices_includes_devices_with_no_items(self) -> None:
        self.seed()

        result = self.run_query(
            IFACES, metrics=[{"op": "count_devices", "alias": "devices"}, {"op": "count_items"}]
        )

        self.assertEqual([c.key for c in result.columns], ["devices", "count_items"])
        self.assertEqual(result.rows, [[3, 3]])

    def test_items_per_device_shows_a_zero_row(self) -> None:
        self.seed()

        result = self.run_query(
            IFACES, group_by=["device_name"], metrics=[{"op": "count_items", "alias": "items"}]
        )

        self.assertEqual(result.rows, [["sw1", 2], ["sw2", 0], ["sw3", 1]])

    def test_plain_count_next_to_a_device_metric_does_not_count_markers(self) -> None:
        self.seed()

        result = self.run_query(
            IFACES, metrics=[{"op": "count"}, {"op": "count_devices", "alias": "devices"}]
        )

        self.assertEqual(result.rows, [[3, 3]])

    def test_a_newer_empty_collection_supersedes_older_items(self) -> None:
        self.add("sw1", "ifaces", [{"name": "a"}], at=NOW - timedelta(days=1))
        self.add("sw1", "ifaces", [])

        result = self.run_query(IFACES, metrics=[{"op": "count_devices"}, {"op": "count_items"}])

        self.assertEqual(result.rows, [[1, 0]])

    def test_device_name_filter_is_allowed_and_applies_to_markers(self) -> None:
        self.seed()

        result = self.run_query(
            IFACES,
            filters=[{"field": "device_name", "op": "eq", "value": "sw2"}],
            metrics=[{"op": "count_devices"}],
        )

        self.assertEqual(result.rows, [[1]])

    def test_history_counts_collections_including_empty_ones(self) -> None:
        self.add("sw1", "ifaces", [{"name": "a"}], at=NOW - timedelta(days=1))
        self.add("sw1", "ifaces", [])

        result = self.run_query(IFACES, scope={"kind": "history"}, metrics=[{"op": "count_items"}])

        self.assertEqual(result.rows, [[1]])

    def test_field_filters_group_by_fields_and_other_metrics_are_rejected(self) -> None:
        for extra in (
            {"filters": [{"field": "status", "op": "eq", "value": "up"}]},
            {"group_by": ["status"]},
        ):
            with self.subTest(extra=extra), self.assertRaises(ReportQueryError):
                self.run_query(IFACES, **{"metrics": [{"op": "count_devices"}], **extra})
        with self.assertRaises(ReportQueryError):
            self.run_query(
                IFACES,
                metrics=[{"op": "count_devices"}, {"op": "count_missing", "field": "status"}],
            )

    def test_the_new_ops_take_no_field(self) -> None:
        with self.assertRaises(ValueError):
            ReportQuery.model_validate(
                {"dataset": "ifaces", "metrics": [{"op": "count_devices", "field": "status"}]}
            )
