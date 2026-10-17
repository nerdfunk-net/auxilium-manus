"""Entry point of the Reports app for listing sources, reading catalogs and running queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.reports import DatasetInfo, QueryResult, ReportQuery, SourceInfo
from services.reports.errors import ReportQueryError
from services.reports.sources.base import ReportSource
from services.reports.sources.registry import get_source, list_sources


class ReportQueryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sources(self) -> list[SourceInfo]:
        return list_sources()

    def catalog(self, source_id: str) -> list[DatasetInfo]:
        return get_source(source_id, db=self.db).describe()

    def validate(self, source_id: str, query: ReportQuery) -> None:
        """Check a query against the catalog without running it (raises ``ReportQueryError``)."""
        self._source_for(source_id, query).validate(query)

    def run(self, source_id: str, query: ReportQuery) -> QueryResult:
        return self._source_for(source_id, query).run(query)

    def _source_for(self, source_id: str, query: ReportQuery) -> ReportSource:
        source = get_source(source_id, db=self.db)
        if query.source != source_id:
            raise ReportQueryError(
                f"query source {query.source!r} does not match the requested source {source_id!r}"
            )
        return source
