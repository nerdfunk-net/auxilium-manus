"""The report database as a report source (``report_data_records`` + the dataset catalog)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.reports import DatasetInfo, QueryResult, ReportQuery
from repositories.report_data_records_repository import ReportDataRecordRepository
from repositories.report_datasets_repository import ReportDatasetRepository
from services.reports.errors import ReportQueryError
from services.reports.field_stats import infer_fields
from services.reports.query_compiler import compile_query, execute_query

SOURCE_ID = "report_data"
# Field types and sample values come from this many of the newest rows of a dataset.
SAMPLE_ROWS = 200


class ReportDataSource:
    id = SOURCE_ID
    label = "Report database"

    def __init__(self, db: Session) -> None:
        self.db = db
        self._records = ReportDataRecordRepository(db)
        self._datasets = ReportDatasetRepository(db)

    def describe(self) -> list[DatasetInfo]:
        return [self._describe(entry) for entry in self._datasets.list_all()]

    def validate(self, query: ReportQuery) -> None:
        compile_query(query, self._dataset(query), dialect=self.db.get_bind().dialect.name)

    def run(self, query: ReportQuery) -> QueryResult:
        return execute_query(self.db, query, self._dataset(query))

    def _dataset(self, query: ReportQuery) -> DatasetInfo:
        entry = self._datasets.get(query.dataset)
        if entry is None:
            raise ReportQueryError(f"unknown dataset {query.dataset!r}")
        return self._describe(entry)

    def _describe(self, entry) -> DatasetInfo:  # type: ignore[no-untyped-def]
        sample = [
            row.data
            for row in self._records.recent_rows(entry.dataset, limit=SAMPLE_ROWS)
            if isinstance(row.data, dict)
        ]
        return DatasetInfo(
            name=entry.dataset,
            mode=entry.mode,
            fields=infer_fields(sample, list(entry.field_names)),
            last_collected_at=entry.last_collected_at,
        )
