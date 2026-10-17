"""Report definitions and snapshots on real PostgreSQL (JSONB, foreign keys, unique name)."""

from __future__ import annotations

import pytest

import core.database as db_mod
from models.report_definitions import (
    ReportDefinitionCreate,
    ReportSection,
    ReportSnapshotResponse,
)
from models.reports import ReportQuery
from services.report_data.report_data_service import ReportDataService
from services.reports.report_service import ReportNameConflictError, ReportService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("require_postgres", "clean_tables"),
]


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _payload(name: str = "Fleet") -> ReportDefinitionCreate:
    query = ReportQuery(
        dataset="inventory", group_by=["location"], metrics=[{"op": "count", "alias": "devices"}]
    )
    return ReportDefinitionCreate(
        name=name, sections=[ReportSection(id="loc", title="Per location", query=query)]
    )


def test_generate_and_keep_snapshot_after_definition_delete(session) -> None:
    data = ReportDataService(session)
    for device, location in [("sw1", "dc1"), ("sw2", "dc1"), ("sw3", "dc2")]:
        data.record_device_data(
            device_name=device, dataset="inventory", data={"location": location}
        )
    service = ReportService(session)
    definition = service.create_definition(_payload(), actor_id=None)

    snapshot = service.generate(definition.id, actor_name="alice")
    content = ReportSnapshotResponse.model_validate(snapshot).content
    assert content.sections[0].result is not None
    assert sorted(content.sections[0].result.rows) == [["dc1", 2], ["dc2", 1]]
    assert service.list_definitions()[0].snapshot_count == 1

    service.delete_definition(definition.id)

    session.expire_all()
    kept = service.get_snapshot(snapshot.id)
    assert kept.definition_id is None
    assert kept.content["name"] == "Fleet"


def test_unique_name_is_enforced_by_the_database(session) -> None:
    service = ReportService(session)
    service.create_definition(_payload(), actor_id=None)
    with pytest.raises(ReportNameConflictError):
        service.create_definition(_payload(), actor_id=None)
    # the session is still usable after the failed insert
    assert len(service.list_definitions()) == 1


def test_template_body_and_template_delete_on_postgres(session) -> None:
    from core.models.templates import Template

    template = Template(
        name="exec",
        category="report",
        template_type="jinja2",
        content="{{ report.name }}: {{ sections.loc.row_count }} sites",
    )
    session.add(template)
    session.commit()
    data = ReportDataService(session)
    data.record_device_data(device_name="sw1", dataset="inventory", data={"location": "dc1"})
    service = ReportService(session)
    payload = _payload()
    payload = payload.model_copy(update={"template_id": template.id})
    definition = service.create_definition(payload, actor_id=None)

    snapshot = service.generate(definition.id, actor_name="alice")

    body = ReportSnapshotResponse.model_validate(snapshot).content.body
    assert body is not None and body.markdown == "Fleet: 1 sites"
    session.delete(template)
    session.commit()
    session.expire_all()
    # A fresh database sets template_id to NULL (foreign key); one migrated from an older version
    # keeps the dangling id. Both must still generate a report with the default template.
    again = service.generate(definition.id, actor_name="alice")
    again_body = ReportSnapshotResponse.model_validate(again).content.body
    assert again_body is not None and (again_body.markdown or "").startswith("# Fleet")
