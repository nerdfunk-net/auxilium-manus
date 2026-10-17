"""ReportService: definition CRUD, snapshot generation, failure isolation."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from core.models.templates import Template
from models.report_definitions import (
    SNAPSHOT_ROW_CAP,
    ReportDefinitionCreate,
    ReportDefinitionUpdate,
    ReportSection,
    ReportSnapshotResponse,
)
from models.reports import QueryResult, ReportQuery, ResultColumn
from services.reports.errors import ReportQueryError
from services.reports.report_service import (
    InvalidReportError,
    ReportNameConflictError,
    ReportNotFoundError,
    ReportService,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ReportDataRecord.__table__,
            ReportDataset.__table__,
            ReportDefinition.__table__,
            ReportSnapshot.__table__,
            Template.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(ReportDataset(dataset="inventory", mode="device", field_names=["location"]))
    for i, loc in enumerate(["dc1", "dc1", "dc2"]):
        session.add(
            ReportDataRecord(
                device_name=f"sw{i}",
                dataset="inventory",
                data={"location": loc},
                collection_id=f"c{i}",
            )
        )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _section(sid: str = "per-location", dataset: str = "inventory", **kw) -> ReportSection:
    query = ReportQuery(
        dataset=dataset, group_by=["location"], metrics=[{"op": "count", "alias": "devices"}]
    )
    return ReportSection(id=sid, title=sid, query=query, **kw)


def _create(service: ReportService, name: str = "Fleet", sections=None):
    sections = [_section()] if sections is None else sections
    return service.create_definition(
        ReportDefinitionCreate(name=name, sections=sections), actor_id=None
    )


def test_create_get_list(db: Session) -> None:
    service = ReportService(db)
    created = _create(service)

    assert created.name == "Fleet"
    assert created.sections[0]["id"] == "per-location"
    assert service.get_definition(created.id).id == created.id
    summaries = service.list_definitions()
    assert [(s.name, s.section_count, s.snapshot_count) for s in summaries] == [("Fleet", 1, 0)]
    assert summaries[0].last_generated_at is None


def test_get_missing_raises(db: Session) -> None:
    with pytest.raises(ReportNotFoundError):
        ReportService(db).get_definition(42)


def test_duplicate_name_conflicts(db: Session) -> None:
    service = ReportService(db)
    _create(service)
    with pytest.raises(ReportNameConflictError):
        _create(service)


def test_rename_to_existing_name_conflicts(db: Session) -> None:
    service = ReportService(db)
    _create(service, "A")
    b = _create(service, "B")
    with pytest.raises(ReportNameConflictError):
        service.update_definition(b.id, ReportDefinitionUpdate(name="A"))
    # the failed update did not poison the session
    assert service.get_definition(b.id).name == "B"


def test_update_changes_only_sent_fields(db: Session) -> None:
    service = ReportService(db)
    d = _create(service)
    updated = service.update_definition(d.id, ReportDefinitionUpdate(description="new"))
    assert updated.description == "new"
    assert updated.name == "Fleet"
    assert len(updated.sections) == 1


def test_unknown_source_is_rejected(db: Session) -> None:
    section = _section()
    section.query = section.query.model_copy(update={"source": "nope"})
    with pytest.raises(InvalidReportError):
        _create(ReportService(db), sections=[section])


def test_generate_stores_snapshot_with_results(db: Session) -> None:
    service = ReportService(db)
    d = _create(service)

    snap = service.generate(d.id, actor_name="alice")

    assert snap.status == "complete"
    assert snap.generated_by == "alice"
    assert snap.definition_id == d.id
    assert snap.name.startswith("Fleet")
    content = ReportSnapshotResponse.model_validate(snap).content
    section = content.sections[0]
    assert section.status == "ok"
    assert section.result is not None
    assert sorted(section.result.rows) == [["dc1", 2], ["dc2", 1]]
    assert service.list_definitions()[0].snapshot_count == 1


def test_one_failing_section_makes_a_partial_snapshot(db: Session) -> None:
    service = ReportService(db)
    d = _create(service, sections=[_section("ok"), _section("bad", dataset="missing")])

    snap = service.generate(d.id, actor_name="alice")

    assert snap.status == "partial"
    sections = ReportSnapshotResponse.model_validate(snap).content.sections
    assert [s.status for s in sections] == ["ok", "error"]
    assert sections[1].result is None
    assert sections[1].error


def test_unexpected_error_is_hidden_in_snapshot(db: Session, monkeypatch) -> None:
    def boom(self, source_id, query):
        raise RuntimeError("secret internals")

    monkeypatch.setattr("services.reports.report_query_service.ReportQueryService.run", boom)
    service = ReportService(db)
    d = _create(service)

    snap = service.generate(d.id, actor_name="alice")

    section = ReportSnapshotResponse.model_validate(snap).content.sections[0]
    assert section.status == "error"
    assert "secret internals" not in (section.error or "")


def test_query_error_message_is_kept(db: Session, monkeypatch) -> None:
    def bad(self, source_id, query):
        raise ReportQueryError("unknown field 'x'")

    monkeypatch.setattr("services.reports.report_query_service.ReportQueryService.run", bad)
    service = ReportService(db)
    d = _create(service)
    section = ReportSnapshotResponse.model_validate(
        service.generate(d.id, actor_name="a")
    ).content.sections[0]
    assert section.error == "unknown field 'x'"


def test_rows_are_capped_per_section(db: Session, monkeypatch) -> None:
    rows = [[i] for i in range(SNAPSHOT_ROW_CAP + 5)]

    def big(self, source_id, query):
        return QueryResult(columns=[ResultColumn(key="n", label="n", type="number")], rows=rows)

    monkeypatch.setattr("services.reports.report_query_service.ReportQueryService.run", big)
    service = ReportService(db)
    d = _create(service)
    section = ReportSnapshotResponse.model_validate(
        service.generate(d.id, actor_name="a")
    ).content.sections[0]
    assert section.result is not None
    assert len(section.result.rows) == SNAPSHOT_ROW_CAP
    assert section.truncated is True


def test_generate_missing_definition(db: Session) -> None:
    with pytest.raises(ReportNotFoundError):
        ReportService(db).generate(9, actor_name="a")


def test_snapshot_survives_definition_delete(db: Session) -> None:
    service = ReportService(db)
    d = _create(service)
    snap = service.generate(d.id, actor_name="a")

    service.delete_definition(d.id)

    kept = service.get_snapshot(snap.id)
    assert kept.content["name"] == "Fleet"
    assert [s.id for s in service.list_snapshots()] == [snap.id]


def test_delete_snapshot(db: Session) -> None:
    service = ReportService(db)
    snap = service.generate(_create(service).id, actor_name="a")
    service.delete_snapshot(snap.id)
    with pytest.raises(ReportNotFoundError):
        service.get_snapshot(snap.id)
    with pytest.raises(ReportNotFoundError):
        service.delete_snapshot(snap.id)


def test_old_snapshots_are_pruned(db: Session, monkeypatch) -> None:
    monkeypatch.setattr("services.reports.report_service.MAX_SNAPSHOTS_PER_DEFINITION", 2)
    service = ReportService(db)
    d = _create(service)
    ids = [service.generate(d.id, actor_name="a").id for _ in range(3)]
    kept = [s.id for s in service.list_snapshots(definition_id=d.id)]
    assert kept == [ids[2], ids[1]]


def test_size_limit_marks_section_as_error(db: Session, monkeypatch) -> None:
    monkeypatch.setattr("services.reports.report_service.MAX_SNAPSHOT_BYTES", 10)
    service = ReportService(db)
    snap = service.generate(_create(service).id, actor_name="a")
    section = ReportSnapshotResponse.model_validate(snap).content.sections[0]
    assert snap.status == "partial"
    assert section.status == "error"


def test_non_finite_numbers_become_null(db: Session, monkeypatch) -> None:
    def nan(self, source_id, query):
        return QueryResult(
            columns=[ResultColumn(key="n", label="n", type="number")],
            rows=[[float("nan")], [float("inf")], [1.5]],
        )

    monkeypatch.setattr("services.reports.report_query_service.ReportQueryService.run", nan)
    service = ReportService(db)
    snap = service.generate(_create(service).id, actor_name="a")
    section = ReportSnapshotResponse.model_validate(snap).content.sections[0]
    assert section.result is not None
    assert section.result.rows == [[None], [None], [1.5]]


def _template(db: Session, content: str, *, category: str = "report", active: bool = True) -> int:
    row = Template(
        name=f"t{db.query(Template).count()}",
        category=category,
        template_type="jinja2",
        content=content,
        is_active=active,
    )
    db.add(row)
    db.commit()
    return row.id


def _create_with(service: ReportService, template_id: int | None):
    return service.create_definition(
        ReportDefinitionCreate(name="Fleet", sections=[_section()], template_id=template_id),
        actor_id=None,
    )


def test_template_must_exist_be_active_and_a_report_template(db: Session) -> None:
    service = ReportService(db)

    for bad in (
        999,
        _template(db, "x", category="netmiko"),
        _template(db, "x", active=False),
    ):
        with pytest.raises(InvalidReportError):
            _create_with(service, bad)

    with pytest.raises(InvalidReportError):
        service.update_definition(
            _create_with(service, None).id, ReportDefinitionUpdate(template_id=999)
        )


def test_template_can_be_set_and_cleared(db: Session) -> None:
    service = ReportService(db)
    template_id = _template(db, "x")
    created = _create_with(service, template_id)
    assert created.template_id == template_id

    cleared = service.update_definition(created.id, ReportDefinitionUpdate(template_id=None))

    assert cleared.template_id is None


def test_generate_without_a_template_renders_the_default(db: Session) -> None:
    service = ReportService(db)
    snap = service.generate(_create_with(service, None).id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snap).content.body
    assert body is not None and body.error is None
    assert body.template_id is None
    assert body.markdown is not None
    assert body.markdown.startswith("# Fleet")
    assert "| dc1 | 2 |" in body.markdown
    assert snap.status == "complete"


def test_generate_renders_the_chosen_template(db: Session) -> None:
    service = ReportService(db)
    template_id = _template(
        db,
        "{{ report.name }} has {{ sections['per-location'].row_count }} sites, "
        "made by {{ report.generated_by }}.",
    )
    snap = service.generate(_create_with(service, template_id).id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snap).content.body
    assert body is not None
    assert body.markdown == "Fleet has 2 sites, made by alice."
    assert body.template_id == template_id
    assert body.template_name.startswith("t")


def test_a_broken_template_gives_a_partial_snapshot_with_the_error(db: Session) -> None:
    service = ReportService(db)
    template_id = _template(db, "{{ sections.missing.rows }}")
    snap = service.generate(_create_with(service, template_id).id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snap).content.body
    assert snap.status == "partial"
    assert body is not None and body.markdown is None and body.error
    # the section results are kept even though the body could not be rendered
    assert ReportSnapshotResponse.model_validate(snap).content.sections[0].status == "ok"


def test_a_template_that_became_inactive_falls_back_to_the_default_with_a_notice(
    db: Session,
) -> None:
    service = ReportService(db)
    template_id = _template(db, "x")
    definition = _create_with(service, template_id)
    db.query(Template).update({"is_active": False})
    db.commit()

    snap = service.generate(definition.id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snap).content.body
    assert snap.status == "partial"
    assert body is not None and body.markdown is not None
    assert body.markdown.startswith("# Fleet")  # the default template
    assert "no longer exists" in (body.error or "")


def test_preview_renders_unsaved_template_text_against_a_snapshot(db: Session) -> None:
    service = ReportService(db)
    snap = service.generate(_create_with(service, None).id, actor_name="alice")

    ok = service.preview_template(
        snap.id, "{{ report.name }}/{{ sections['per-location'].row_count }}"
    )
    bad = service.preview_template(snap.id, "{{ nope.x }}")

    assert (ok.markdown, ok.error) == ("Fleet/2", None)
    assert bad.markdown is None and bad.error


def test_preview_of_a_missing_snapshot(db: Session) -> None:
    with pytest.raises(ReportNotFoundError):
        ReportService(db).preview_template(99, "x")


def test_a_template_that_is_no_longer_a_report_template_is_not_rendered(db: Session) -> None:
    service = ReportService(db)
    template_id = _template(db, "SECRET-DEVICE-TEXT")
    definition = _create_with(service, template_id)
    db.query(Template).update({"category": "netmiko"})
    db.commit()

    snap = service.generate(definition.id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snap).content.body
    assert snap.status == "partial"
    assert body is not None and body.markdown is not None
    assert "SECRET-DEVICE-TEXT" not in body.markdown
    assert "no longer" in (body.error or "")
