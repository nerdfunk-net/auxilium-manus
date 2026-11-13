"""Lookup of the available report sources."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.reports import SourceInfo
from services.reports.errors import UnknownSourceError
from services.reports.sources.base import ReportSource
from services.reports.sources.nautobot_source import NautobotReportSource
from services.reports.sources.report_data_source import ReportDataSource

_SOURCES: tuple[type[ReportDataSource] | type[NautobotReportSource], ...] = (
    ReportDataSource,
    NautobotReportSource,
)


def list_sources() -> list[SourceInfo]:
    return [SourceInfo(id=source.id, label=source.label) for source in _SOURCES]


def get_source(
    source_id: str, *, db: Session, actor_user_id: int | None = None
) -> ReportSource:
    """The source with that id. ``actor_user_id`` is the user a source that calls an external
    system (Nautobot) acts as; the report database ignores it."""
    if source_id == ReportDataSource.id:
        return ReportDataSource(db)
    if source_id == NautobotReportSource.id:
        return NautobotReportSource(db, actor_user_id=actor_user_id)
    raise UnknownSourceError(source_id)


# A source that reads an external system also needs that system's own permission: generating a
# report checks it, and so does reading a stored snapshot (its rows came from that system).
SOURCE_PERMISSIONS: dict[str, tuple[str, str]] = {
    NautobotReportSource.id: ("sources.nautobot", "read"),
}
