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
from repositories.templates_repository import TemplatesRepository
from services.ai_assistant.tools.report_tools import ReportAccessError, ReportNotFoundError
from services.auth.rbac_service import RBACService
from services.reports.errors import ReportQueryError, UnknownSourceError
from services.reports.report_query_service import ReportQueryService
from services.reports.report_service import ReportNotFoundError as SnapshotMissing
from services.reports.report_service import ReportService
from services.reports.template_sections import referenced_sections
from services.templates.categories import CATEGORY_REPORT

RECENT_SNAPSHOTS = 5


class DbReportReader:
    def __init__(self, user_id: int, source_id: str, *, pin_source: bool = False) -> None:
        self._user_id = user_id
        self._source_id = source_id
        # The Reports page works on one source; its assistant may not query another one.
        self._pin_source = pin_source

    def _check_source(self, query: ReportQuery) -> None:
        if self._pin_source and query.source != self._source_id:
            raise ReportQueryError(
                f"this assistant works on the source {self._source_id!r}; "
                f"the query names {query.source!r}"
            )

    def _check(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "reports", "read"):
            raise ReportAccessError

    def _check_templates(self, db: Any) -> None:
        """Report templates are read through the Templates feature, so its permission counts."""
        self._check(db)
        if not RBACService(db).has_permission(self._user_id, "templates", "read"):
            raise ReportAccessError

    async def catalog(self, source_id: str) -> list[DatasetInfo]:
        return await asyncio.to_thread(self._catalog, source_id)

    def _catalog(self, source_id: str) -> list[DatasetInfo]:
        with SessionLocal() as db:
            self._check(db)
            try:
                return ReportQueryService(db, actor_user_id=self._user_id).catalog(source_id)
            except UnknownSourceError as exc:
                raise ReportAccessError from exc

    async def run_query(self, query: ReportQuery) -> QueryResult:
        return await asyncio.to_thread(self._run, query)

    def _run(self, query: ReportQuery) -> QueryResult:
        self._check_source(query)
        with SessionLocal() as db:
            self._check(db)
            try:
                service = ReportQueryService(db, actor_user_id=self._user_id)
                return service.run(query.source, query)
            except UnknownSourceError as exc:
                raise ReportAccessError from exc

    async def validate_query(self, query: ReportQuery) -> None:
        await asyncio.to_thread(self._validate, query)

    def _validate(self, query: ReportQuery) -> None:
        self._check_source(query)
        with SessionLocal() as db:
            self._check(db)
            try:
                ReportQueryService(db, actor_user_id=self._user_id).validate(query.source, query)
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
            service = ReportService(db)
            try:
                snapshot = service.get_snapshot(snapshot_id)
            except SnapshotMissing as exc:
                raise ReportNotFoundError from exc
            rbac = RBACService(db)
            for resource, action in service.required_source_permissions(snapshot):
                if not rbac.has_permission(self._user_id, resource, action):
                    raise ReportAccessError
            return {"id": snapshot.id, "name": snapshot.name, "content": snapshot.content}

    # -- sources and report templates (Ask the Net) ---------------------------------------

    async def list_sources(self) -> list[dict[str, str]]:
        return await asyncio.to_thread(self._list_sources)

    def _list_sources(self) -> list[dict[str, str]]:
        with SessionLocal() as db:
            self._check(db)
            return [s.model_dump() for s in ReportQueryService(db).list_sources()]

    async def list_templates(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_templates)

    def _list_templates(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._check_templates(db)
            rows = TemplatesRepository(db).list_templates(category=CATEGORY_REPORT)
            return [_template_info(t) for t in rows]

    async def get_template(self, template_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_template, template_id)

    def _get_template(self, template_id: int) -> dict[str, Any]:
        with SessionLocal() as db:
            self._check_templates(db)
            template = TemplatesRepository(db).get_by_id(template_id)
            if template is None or not template.is_active or template.category != CATEGORY_REPORT:
                raise ReportNotFoundError
            return _template_info(template)


def _template_info(template: Any) -> dict[str, Any]:
    """What the model may know about a report template: its name and which sections it reads.
    The template text itself stays out."""
    refs = referenced_sections(template.content)
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "section_ids": list(refs.ids),
        "uses_section_list": refs.uses_section_list,
        "dynamic_lookup": refs.dynamic,
    }
