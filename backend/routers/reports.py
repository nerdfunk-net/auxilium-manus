"""Reports: sources, dataset catalogs and queries (doc/REPORTS.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.rate_limit import rate_limited
from models.reports import DatasetInfo, QueryResult, ReportQuery, SourceInfo
from services.reports.errors import ReportQueryError, UnknownSourceError
from services.reports.report_query_service import ReportQueryService

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(get_current_user), Depends(require_permission("reports", "read"))],
)

# Each query reads the report table; keep one user from hammering it.
_QUERY_BUDGET = rate_limited("reports-query", attempts=60, window_seconds=60)
# Reading a catalog samples recent rows of every dataset.
_CATALOG_BUDGET = rate_limited("reports-catalog", attempts=120, window_seconds=60)


def get_report_query_service(db: Session = Depends(get_db)) -> ReportQueryService:
    return ReportQueryService(db)


def _unknown_source(source_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown report source {source_id!r}")


@router.get("/sources", response_model=list[SourceInfo])
def list_sources(
    service: ReportQueryService = Depends(get_report_query_service),
) -> list[SourceInfo]:
    return service.list_sources()


@router.get(
    "/sources/{source_id}/catalog",
    response_model=list[DatasetInfo],
    dependencies=[Depends(_CATALOG_BUDGET)],
)
def get_catalog(
    source_id: str, service: ReportQueryService = Depends(get_report_query_service)
) -> list[DatasetInfo]:
    try:
        return service.catalog(source_id)
    except UnknownSourceError as exc:
        raise _unknown_source(source_id) from exc


@router.post(
    "/sources/{source_id}/query",
    response_model=QueryResult,
    dependencies=[Depends(_QUERY_BUDGET)],
)
def run_query(
    source_id: str,
    body: ReportQuery,
    service: ReportQueryService = Depends(get_report_query_service),
) -> QueryResult:
    try:
        return service.run(source_id, body)
    except UnknownSourceError as exc:
        raise _unknown_source(source_id) from exc
    except ReportQueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
