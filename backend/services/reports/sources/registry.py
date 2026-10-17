"""Lookup of the available report sources."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.reports import SourceInfo
from services.reports.errors import UnknownSourceError
from services.reports.sources.base import ReportSource
from services.reports.sources.report_data_source import ReportDataSource

_SOURCES: tuple[type[ReportDataSource], ...] = (ReportDataSource,)


def list_sources() -> list[SourceInfo]:
    return [SourceInfo(id=source.id, label=source.label) for source in _SOURCES]


def get_source(source_id: str, *, db: Session) -> ReportSource:
    for source in _SOURCES:
        if source.id == source_id:
            return source(db)
    raise UnknownSourceError(source_id)
