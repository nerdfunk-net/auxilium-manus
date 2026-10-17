"""Tests for ReportDataService validation and recording."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from services.report_data.report_data_service import (
    MAX_ITEMS_PER_DEVICE,
    MAX_STRING_LENGTH,
    ReportDataService,
    validate_dataset_name,
    validate_field_name,
)


class ValidationTests(unittest.TestCase):
    def test_field_name_rejects_names_reserved_by_the_reports_app(self) -> None:
        for name in ("device_name", "collected_at", "time_bucket"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reserved"):
                validate_field_name(name)

    def test_dataset_name_accepts_lowercase_slug(self) -> None:
        for name in ("inventory", "inv-2", "device_types", "a"):
            self.assertEqual(validate_dataset_name(name), name)

    def test_dataset_name_is_stripped(self) -> None:
        self.assertEqual(validate_dataset_name("  inventory "), "inventory")

    def test_dataset_name_rejects_bad_values(self) -> None:
        for name in ("", "  ", "Inventory", "-x", "has space", "a.b", "x" * 101):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_dataset_name(name)

    def test_field_name_accepts_snake_case(self) -> None:
        for name in ("serial_number", "os2", "a"):
            self.assertEqual(validate_field_name(name), name)

    def test_field_name_rejects_bad_values(self) -> None:
        for name in ("", "Serial", "2fast", "a-b", "a.b", "x" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_field_name(name)


class ReportDataServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine, tables=[ReportDataRecord.__table__, ReportDataset.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = ReportDataService(self.db)

    def _rows(self) -> list[ReportDataRecord]:
        return list(self.db.query(ReportDataRecord).order_by(ReportDataRecord.id))

    def test_records_scalar_fields(self) -> None:
        data = {"serial": "A1", "ports": 48, "ratio": 0.5, "stacked": True, "site": None}
        self.service.record_device_data(device_name="r1", dataset="inventory", data=data, run_id=7)

        (row,) = self._rows()
        self.assertEqual(row.data, data)
        self.assertEqual(row.run_id, 7)
        self.assertEqual(row.dataset, "inventory")

    def test_run_id_is_optional(self) -> None:
        self.service.record_device_data(
            device_name="r1", dataset="inventory", data={"serial": "A1"}
        )
        self.assertIsNone(self._rows()[0].run_id)

    def test_rejects_nested_values(self) -> None:
        for value in ({"x": 1}, [1, 2], ("a",)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "serial"):
                self.service.record_device_data(
                    device_name="r1", dataset="inventory", data={"serial": value}
                )
        self.assertEqual(self._rows(), [])

    def test_rejects_non_finite_numbers(self) -> None:
        with self.assertRaises(ValueError):
            self.service.record_device_data(
                device_name="r1", dataset="inventory", data={"x": float("nan")}
            )

    def test_rejects_invalid_names_and_empty_data(self) -> None:
        with self.assertRaises(ValueError):
            self.service.record_device_data(device_name="r1", dataset="Bad Name", data={"a": 1})
        with self.assertRaises(ValueError):
            self.service.record_device_data(device_name="r1", dataset="inv", data={"Bad": 1})
        with self.assertRaises(ValueError):
            self.service.record_device_data(device_name="r1", dataset="inv", data={})
        with self.assertRaises(ValueError):
            self.service.record_device_data(device_name="", dataset="inv", data={"a": 1})

    def test_records_one_row_per_item(self) -> None:
        items = [{"name": "Gi1", "status": "up"}, {"name": "Gi2", "status": "disabled"}]
        self.service.record_device_items(
            device_name="r1", dataset="interfaces", items=items, run_id=3
        )

        self.assertEqual([row.data for row in self._rows()], items)
        self.assertEqual({row.collection_id for row in self._rows()}.__len__(), 1)

    def test_no_items_stores_an_empty_marker(self) -> None:
        self.service.record_device_items(device_name="r1", dataset="ntp", items=[])

        (row,) = self._rows()
        self.assertTrue(row.is_empty)

    def test_item_validation_names_the_offending_item(self) -> None:
        with self.assertRaisesRegex(ValueError, "item 1"):
            self.service.record_device_items(
                device_name="r1",
                dataset="ifaces",
                items=[{"name": "Gi1"}, {"name": ["not", "scalar"]}],
            )
        with self.assertRaises(ValueError):
            self.service.record_device_items(device_name="r1", dataset="ifaces", items=[{}])
        self.assertEqual(self._rows(), [])

    def test_rejects_too_many_items(self) -> None:
        items = [{"n": i} for i in range(MAX_ITEMS_PER_DEVICE + 1)]
        with self.assertRaisesRegex(ValueError, "at most"):
            self.service.record_device_items(device_name="r1", dataset="ifaces", items=items)
        self.assertEqual(self._rows(), [])

    def test_rejects_overlong_strings(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most"):
            self.service.record_device_data(
                device_name="r1", dataset="inv", data={"blob": "x" * (MAX_STRING_LENGTH + 1)}
            )
        self.service.record_device_data(
            device_name="r1", dataset="inv", data={"ok": "x" * MAX_STRING_LENGTH}
        )
        self.assertEqual(len(self._rows()), 1)

    def _catalog(self) -> list[ReportDataset]:
        return list(self.db.query(ReportDataset).order_by(ReportDataset.dataset))

    def test_device_write_updates_the_catalog(self) -> None:
        self.service.record_device_data(
            device_name="r1", dataset="inventory", data={"serial": "A", "model": "X"}
        )

        (entry,) = self._catalog()
        self.assertEqual((entry.dataset, entry.mode), ("inventory", "device"))
        self.assertEqual(entry.field_names, ["serial", "model"])

    def test_item_write_updates_the_catalog_even_when_empty(self) -> None:
        self.service.record_device_items(
            device_name="r1", dataset="ntp", items=[], field_names=["address"]
        )

        (entry,) = self._catalog()
        self.assertEqual((entry.dataset, entry.mode), ("ntp", "items"))
        self.assertEqual(entry.field_names, ["address"])

    def test_items_field_names_default_to_the_first_item(self) -> None:
        self.service.record_device_items(
            device_name="r1", dataset="ifaces", items=[{"name": "Gi1", "status": "up"}]
        )
        self.assertEqual(self._catalog()[0].field_names, ["name", "status"])

    def test_failed_catalog_update_does_not_fail_the_write(self) -> None:
        from unittest.mock import patch

        from sqlalchemy.exc import OperationalError

        with (
            patch.object(
                self.service.datasets,
                "upsert",
                side_effect=OperationalError("x", {}, Exception("boom")),
            ),
            self.assertLogs("services.report_data.report_data_service", level="WARNING"),
        ):
            self.service.record_device_data(
                device_name="r1", dataset="inventory", data={"serial": "A"}
            )

        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self._catalog(), [])

    def test_validation_failure_leaves_the_catalog_untouched(self) -> None:
        with self.assertRaises(ValueError):
            self.service.record_device_data(
                device_name="r1", dataset="inventory", data={"serial": ["x"]}
            )
        self.assertEqual(self._catalog(), [])
