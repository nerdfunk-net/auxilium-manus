"""Tests for the report source registry, the report-data source and the query service."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from models.reports import ReportQuery
from services.reports.errors import ReportQueryError, UnknownSourceError
from services.reports.report_query_service import ReportQueryService
from services.reports.sources.registry import get_source, list_sources
from services.reports.sources.report_data_source import SAMPLE_ROWS, ReportDataSource


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine, tables=[ReportDataRecord.__table__, ReportDataset.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self._n = 0

    def catalog(self, dataset: str, mode: str, fields: list[str]) -> None:
        self.db.add(ReportDataset(dataset=dataset, mode=mode, field_names=fields))
        self.db.commit()

    def rows(self, device: str, dataset: str, rows: list[dict]) -> None:
        self._n += 1
        for position, data in enumerate(rows):
            self.db.add(
                ReportDataRecord(
                    device_name=device,
                    dataset=dataset,
                    data=data,
                    collection_id=f"c{self._n}",
                    position=position,
                )
            )
        self.db.commit()


class RegistryTests(unittest.TestCase):
    def test_lists_the_report_data_source(self) -> None:
        assert [(s.id, s.label) for s in list_sources()] == [("report_data", "Report database")]

    def test_unknown_source(self) -> None:
        with self.assertRaises(UnknownSourceError):
            get_source("nope", db=None)  # type: ignore[arg-type]


class ReportDataSourceTests(_Base):
    def test_describe_infers_types_from_recent_rows(self) -> None:
        self.catalog("inventory", "device", ["serial", "ports"])
        self.rows("sw1", "inventory", [{"serial": "A", "ports": 48}])
        self.rows("sw2", "inventory", [{"serial": "B", "ports": 24}])

        (info,) = ReportDataSource(self.db).describe()

        assert (info.name, info.mode) == ("inventory", "device")
        assert [(f.name, f.type) for f in info.fields] == [
            ("serial", "string"),
            ("ports", "number"),
        ]
        assert info.fields[0].sample_values == ["B", "A"]  # newest first
        assert info.last_collected_at is not None

    def test_dataset_without_rows_has_unknown_fields(self) -> None:
        self.catalog("ntp", "items", ["address"])

        (info,) = ReportDataSource(self.db).describe()

        assert [(f.name, f.type) for f in info.fields] == [("address", "unknown")]

    def test_sample_is_bounded(self) -> None:
        self.catalog("inv", "device", ["n"])
        for i in range(SAMPLE_ROWS + 20):
            self.rows(f"sw{i}", "inv", [{"n": i}])

        (info,) = ReportDataSource(self.db).describe()

        # Only the newest SAMPLE_ROWS rows are looked at: the oldest value is not a sample.
        assert "0" not in info.fields[0].sample_values

    def test_run_executes_against_the_described_dataset(self) -> None:
        self.catalog("inventory", "device", ["location"])
        self.rows("sw1", "inventory", [{"location": "dc1"}])
        self.rows("sw2", "inventory", [{"location": "dc1"}])

        result = ReportDataSource(self.db).run(
            ReportQuery(dataset="inventory", group_by=["location"], metrics=[{"op": "count"}])  # type: ignore[list-item]
        )

        assert result.rows == [["dc1", 2]]

    def test_run_unknown_dataset(self) -> None:
        with self.assertRaisesRegex(ReportQueryError, "unknown dataset"):
            ReportDataSource(self.db).run(ReportQuery(dataset="nope"))


class ReportQueryServiceTests(_Base):
    def test_sources_catalog_and_query(self) -> None:
        self.catalog("inventory", "device", ["location"])
        self.rows("sw1", "inventory", [{"location": "dc1"}])
        service = ReportQueryService(self.db)

        assert [s.id for s in service.list_sources()] == ["report_data"]
        assert [d.name for d in service.catalog("report_data")] == ["inventory"]
        result = service.run("report_data", ReportQuery(dataset="inventory"))
        assert result.rows == [["sw1", "dc1"]]

    def test_the_path_source_must_match_the_query_source(self) -> None:
        service = ReportQueryService(self.db)
        with self.assertRaisesRegex(ReportQueryError, "source"):
            service.run("report_data", ReportQuery(source="other", dataset="x"))

    def test_unknown_source(self) -> None:
        with self.assertRaises(UnknownSourceError):
            ReportQueryService(self.db).catalog("nope")


class ValidateTests(_Base):
    def test_validate_checks_the_query_without_running_it(self) -> None:
        self.catalog("inventory", "device", ["location"])
        service = ReportQueryService(self.db)

        service.validate(
            "report_data",
            ReportQuery(dataset="inventory", group_by=["location"], metrics=[{"op": "count"}]),
        )
        with self.assertRaises(ReportQueryError):
            service.validate("report_data", ReportQuery(dataset="inventory", select=["nope"]))
        with self.assertRaises(ReportQueryError):
            service.validate("report_data", ReportQuery(dataset="missing"))
        with self.assertRaises(ReportQueryError):
            service.validate("report_data", ReportQuery(source="other", dataset="inventory"))
        with self.assertRaises(UnknownSourceError):
            service.validate("other", ReportQuery(source="other", dataset="inventory"))
