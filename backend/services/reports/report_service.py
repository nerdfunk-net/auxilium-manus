"""Report definitions and snapshots: CRUD plus generation (doc/REPORTS.md).

Generating a report runs every section's query through ``ReportQueryService`` and stores the
definition together with the results as an immutable snapshot. A section that fails does not
fail the report; the snapshot is ``partial`` and the section carries the reason.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from models.report_definitions import (
    SNAPSHOT_ROW_CAP,
    ReportDefinitionCreate,
    ReportDefinitionSummary,
    ReportDefinitionUpdate,
    ReportSection,
    SnapshotBody,
    SnapshotContent,
    SnapshotSection,
)
from models.reports import QueryResult
from repositories.report_definitions_repository import ReportDefinitionsRepository
from repositories.report_snapshots_repository import ReportSnapshotsRepository
from repositories.templates_repository import TemplatesRepository
from services.reports.errors import ReportQueryError, UnknownSourceError
from services.reports.report_query_service import ReportQueryService
from services.reports.report_renderer import (
    DEFAULT_TEMPLATE,
    BodyOutcome,
    build_render_context,
    render_report_body,
)
from services.reports.sources.registry import list_sources
from services.templates.categories import CATEGORY_REPORT

logger = logging.getLogger(__name__)

# Snapshots are kept per report; older ones are pruned when a new one is generated.
MAX_SNAPSHOTS_PER_DEFINITION = 50
# Serialized size a whole snapshot may reach; a section that would exceed it is recorded as failed.
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_SIZE_ERROR = "Not stored: the snapshot size limit was reached. Narrow the query or add filters."
_TEMPLATE_GONE = (
    "The report template no longer exists or is inactive; the default template was used."
)
_GENERIC_SECTION_ERROR = "The query could not be run. See the server log."
_NAME_SUFFIX_FORMAT = "%Y-%m-%d %H:%M UTC"


class ReportNotFoundError(LookupError):
    """No report definition or snapshot with that id."""


class ReportNameConflictError(ValueError):
    """Another report definition already has that name."""


class InvalidReportError(ValueError):
    """The definition cannot be saved (for example a section names an unknown source)."""


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.definitions = ReportDefinitionsRepository(db)
        self.snapshots = ReportSnapshotsRepository(db)
        self.queries = ReportQueryService(db)
        self.templates = TemplatesRepository(db)

    # -- definitions ----------------------------------------------------------------------

    def list_definitions(self) -> list[ReportDefinitionSummary]:
        stats = self.snapshots.stats_by_definition()
        summaries = []
        for d in self.definitions.list_all():
            count, last = stats.get(d.id, (0, None))
            summaries.append(
                ReportDefinitionSummary(
                    id=d.id,
                    name=d.name,
                    description=d.description,
                    section_count=len(d.sections),
                    updated_at=d.updated_at,
                    snapshot_count=count,
                    last_generated_at=last,
                )
            )
        return summaries

    def get_definition(self, definition_id: int) -> ReportDefinition:
        definition = self.definitions.get(definition_id)
        if definition is None:
            raise ReportNotFoundError(f"report {definition_id} not found")
        return definition

    def create_definition(
        self, payload: ReportDefinitionCreate, *, actor_id: int | None
    ) -> ReportDefinition:
        self._check_sources(payload.sections)
        self._check_template(payload.template_id)
        if self.definitions.get_by_name(payload.name) is not None:
            raise ReportNameConflictError(payload.name)
        try:
            return self.definitions.create(
                name=payload.name,
                description=payload.description,
                sections=_dump_sections(payload.sections),
                template_id=payload.template_id,
                default_recipients=payload.default_recipients,
                created_by=actor_id,
            )
        except IntegrityError as exc:
            raise self._integrity_error(payload.name, exc) from exc

    def update_definition(
        self, definition_id: int, payload: ReportDefinitionUpdate
    ) -> ReportDefinition:
        definition = self.get_definition(definition_id)
        name_before = definition.name
        changes: dict[str, Any] = {}
        if "name" in payload.model_fields_set and payload.name is not None:
            other = self.definitions.get_by_name(payload.name)
            if other is not None and other.id != definition.id:
                raise ReportNameConflictError(payload.name)
            changes["name"] = payload.name
        if "description" in payload.model_fields_set:
            changes["description"] = payload.description
        if "sections" in payload.model_fields_set and payload.sections is not None:
            self._check_sources(payload.sections)
            changes["sections"] = _dump_sections(payload.sections)
        if payload.default_recipients is not None:
            changes["default_recipients"] = payload.default_recipients
        if "template_id" in payload.model_fields_set:
            self._check_template(payload.template_id)
            changes["template_id"] = payload.template_id
        try:
            return self.definitions.update(definition, **changes)
        except IntegrityError as exc:
            raise self._integrity_error(changes.get("name", name_before), exc) from exc

    def delete_definition(self, definition_id: int) -> None:
        definition = self.get_definition(definition_id)
        # One commit (inside delete): a failed delete must not leave the snapshots detached.
        self.snapshots.detach_definition(definition.id)
        self.definitions.delete(definition)

    # -- snapshots ------------------------------------------------------------------------

    def generate(self, definition_id: int, *, actor_name: str | None) -> ReportSnapshot:
        definition = self.get_definition(definition_id)
        # Plain values first: a rollback while running a section expires the ORM object.
        def_id, def_name, def_description = definition.id, definition.name, definition.description
        def_template_id = definition.template_id
        sections = [ReportSection.model_validate(raw) for raw in definition.sections]
        results: list[SnapshotSection] = []
        used_bytes = 0
        for section in sections:
            outcome = self._run_section(section)
            size = len(json.dumps(outcome.model_dump(mode="json")))
            if used_bytes + size > MAX_SNAPSHOT_BYTES:
                outcome = SnapshotSection(section=section, status="error", error=_SIZE_ERROR)
                size = len(json.dumps(outcome.model_dump(mode="json")))
            used_bytes += size
            results.append(outcome)
        generated_at = datetime.now(UTC)
        body = self._render_body(
            template_id=def_template_id,
            name=def_name,
            description=def_description,
            generated_at=generated_at,
            generated_by=actor_name,
            sections=results,
        )
        content = SnapshotContent(
            name=def_name, description=def_description, sections=results, body=body
        )
        all_ok = all(r.status == "ok" for r in results) and body.error is None
        stamp = generated_at.strftime(_NAME_SUFFIX_FORMAT)
        snapshot = self.snapshots.create(
            definition_id=def_id,
            name=f"{def_name} - {stamp}",
            generated_by=actor_name,
            generated_at=generated_at,
            status="complete" if all_ok else "partial",
            content=content.model_dump(mode="json"),
        )
        self.snapshots.prune(def_id, MAX_SNAPSHOTS_PER_DEFINITION)
        return snapshot

    def list_snapshots(self, *, definition_id: int | None = None) -> list[ReportSnapshot]:
        return self.snapshots.list_snapshots(definition_id=definition_id)

    def get_snapshot(self, snapshot_id: int) -> ReportSnapshot:
        snapshot = self.snapshots.get(snapshot_id)
        if snapshot is None:
            raise ReportNotFoundError(f"snapshot {snapshot_id} not found")
        return snapshot

    def preview_template(self, snapshot_id: int, template_content: str) -> BodyOutcome:
        """Render unsaved template text against a stored snapshot (the template editor's preview).
        Nothing is stored."""
        snapshot = self.get_snapshot(snapshot_id)
        content = SnapshotContent.model_validate(snapshot.content)
        context = build_render_context(
            name=content.name,
            description=content.description,
            generated_at=snapshot.generated_at,
            generated_by=snapshot.generated_by,
            sections=content.sections,
        )
        return render_report_body(template_content, context)

    def delete_snapshot(self, snapshot_id: int) -> None:
        self.snapshots.delete(self.get_snapshot(snapshot_id))

    # -- helpers --------------------------------------------------------------------------

    def _check_template(self, template_id: int | None) -> None:
        if template_id is None:
            return
        template = self.templates.get_by_id(template_id)
        if template is None or not template.is_active or template.category != CATEGORY_REPORT:
            raise InvalidReportError(f"template {template_id} is not an active report template")

    def _render_body(
        self,
        *,
        template_id: int | None,
        name: str,
        description: str | None,
        generated_at: datetime,
        generated_by: str | None,
        sections: list[SnapshotSection],
    ) -> SnapshotBody:
        template_name = ""
        content = DEFAULT_TEMPLATE
        notice: str | None = None
        if template_id is not None:
            template = self.templates.get_by_id(template_id)
            if template is None or not template.is_active or template.category != CATEGORY_REPORT:
                # Databases created before the foreign key existed keep a dangling id; either way
                # the report must still be generated, and the reader is told which template ran.
                notice = _TEMPLATE_GONE
            else:
                template_name, content = template.name, template.content
        context = build_render_context(
            name=name,
            description=description,
            generated_at=generated_at,
            generated_by=generated_by,
            sections=sections,
        )
        outcome = render_report_body(content, context)
        return SnapshotBody(
            template_id=template_id,
            template_name=template_name,
            markdown=outcome.markdown,
            error=outcome.error or notice,
        )

    def _check_sources(self, sections: list[ReportSection]) -> None:
        known = {s.id for s in list_sources()}
        for section in sections:
            if section.query.source not in known:
                raise InvalidReportError(
                    f"section {section.id!r} uses unknown source {section.query.source!r}"
                )

    def _integrity_error(self, name: str, exc: IntegrityError) -> Exception:
        """A name conflict if another report now has that name, else the original error."""
        self.db.rollback()
        if self.definitions.get_by_name(name) is not None:
            return ReportNameConflictError(name)
        return exc

    def _run_section(self, section: ReportSection) -> SnapshotSection:
        try:
            result = self.queries.run(section.query.source, section.query)
        except (ReportQueryError, UnknownSourceError) as exc:
            self.db.rollback()
            # These messages describe the query, not the server, so they are safe to store.
            return SnapshotSection(section=section, status="error", error=str(exc))
        except Exception:
            logger.exception("Report section %s failed", section.id)
            self.db.rollback()
            return SnapshotSection(section=section, status="error", error=_GENERIC_SECTION_ERROR)
        result = _finite(result)
        truncated = result.truncated
        if len(result.rows) > SNAPSHOT_ROW_CAP:
            result = result.model_copy(update={"rows": result.rows[:SNAPSHOT_ROW_CAP]})
            truncated = True
        return SnapshotSection(section=section, status="ok", result=result, truncated=truncated)


def _dump_sections(sections: list[ReportSection]) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in sections]


def _finite(result: QueryResult) -> QueryResult:
    """Replace NaN/Infinity cells by None: JSONB cannot store them."""
    if all(not isinstance(c, float) or math.isfinite(c) for row in result.rows for c in row):
        return result
    rows = [
        [None if isinstance(c, float) and not math.isfinite(c) else c for c in r]
        for r in result.rows
    ]
    return result.model_copy(update={"rows": rows})
