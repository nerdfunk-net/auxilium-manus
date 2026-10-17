"""Report-backed ``ReportReader`` for the report tools.

Runs as the calling user: ``reports:read`` is checked on every call. Each call opens a short-lived
session in a worker thread (the tools are async; the report queries are blocking SQLAlchemy).
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.database import SessionLocal
from models.report_definitions import ReportSection
from models.reports import DatasetInfo, QueryResult, ReportQuery
from services.ai_assistant.tools.report_tools import ReportAccessError, ReportNotFoundError
from services.auth.rbac_service import RBACService
from services.reports.errors import UnknownSourceError
from services.reports.report_query_service import ReportQueryService
from services.reports.report_service import ReportNotFoundError as SnapshotMissing
from services.reports.report_service import ReportService

RECENT_SNAPSHOTS = 5


class DbReportReader:
    def __init__(self, user_id: int, source_id: str) -> None:
        self._user_id = user_id
        self._source_id = source_id

    def _check(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "reports", "read"):
            raise ReportAccessError

    async def catalog(self, source_id: str) -> list[DatasetInfo]:
        return await asyncio.to_thread(self._catalog, source_id)

    def _catalog(self, source_id: str) -> list[DatasetInfo]:
        with SessionLocal() as db:
            self._check(db)
            try:
                return ReportQueryService(db).catalog(source_id)
            except UnknownSourceError as exc:
                raise ReportAccessError from exc

    async def run_query(self, query: ReportQuery) -> QueryResult:
        return await asyncio.to_thread(self._run, query)

    def _run(self, query: ReportQuery) -> QueryResult:
        with SessionLocal() as db:
            self._check(db)
            try:
                return ReportQueryService(db).run(self._source_id, query)
            except UnknownSourceError as exc:
                raise ReportAccessError from exc

    async def validate_query(self, query: ReportQuery) -> None:
        await asyncio.to_thread(self._validate, query)

    def _validate(self, query: ReportQuery) -> None:
        with SessionLocal() as db:
            self._check(db)
            try:
                ReportQueryService(db).validate(self._source_id, query)
            except UnknownSourceError as exc:
                raise ReportAccessError from exc

    async def list_reports(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_reports)

    def _list_reports(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._check(db)
            service = ReportService(db)
            out: list[dict[str, Any]] = []
            for summary in service.list_definitions():
                definition = service.get_definition(summary.id)
                sections = [ReportSection.model_validate(raw) for raw in definition.sections]
                snapshots = service.list_snapshots(definition_id=summary.id)[:RECENT_SNAPSHOTS]
                out.append(
                    {
                        "id": summary.id,
                        "name": summary.name,
                        "sections": [
                            {"id": s.id, "title": s.title, "dataset": s.query.dataset}
                            for s in sections
                        ],
                        "snapshots": [
                            {"id": s.id, "status": s.status, "generated_at": s.generated_at}
                            for s in snapshots
                        ],
                    }
                )
            return out

    async def get_report(self, report_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_report, report_id)

    def _get_report(self, report_id: int) -> dict[str, Any]:
        with SessionLocal() as db:
            self._check(db)
            try:
                definition = ReportService(db).get_definition(report_id)
            except SnapshotMissing as exc:
                raise ReportNotFoundError from exc
            sections = [ReportSection.model_validate(raw) for raw in definition.sections]
            return {
                "id": definition.id,
                "name": definition.name,
                "sections": [{"id": s.id, "title": s.title} for s in sections],
            }

    async def get_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_snapshot, snapshot_id)

    def _get_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        with SessionLocal() as db:
            self._check(db)
            try:
                snapshot = ReportService(db).get_snapshot(snapshot_id)
            except SnapshotMissing as exc:
                raise ReportNotFoundError from exc
            return {"id": snapshot.id, "name": snapshot.name, "content": snapshot.content}
