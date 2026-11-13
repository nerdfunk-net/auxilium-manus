"""DbReportReader: sources and report templates, as the calling user."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from core.models.templates import Template
from models.reports import ReportQuery
from services.ai_assistant import report_reader as module
from services.ai_assistant.report_reader import DbReportReader
from services.ai_assistant.tools.report_tools import ReportAccessError, ReportNotFoundError
from services.auth.rbac_service import RBACService

LAYOUT = '# {{ report.name }}\n{{ sections["devices"].table }}\n{{ sections.totals.value }}'


@pytest.fixture
def granted(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    perms = {"reports:read", "templates:read"}
    monkeypatch.setattr(
        RBACService, "has_permission", lambda self, uid, res, act: f"{res}:{act}" in perms
    )
    return perms


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch, granted: set[str]) -> DbReportReader:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine, tables=[Template.__table__, ReportDefinition.__table__, ReportSnapshot.__table__]
    )
    maker = sessionmaker(bind=engine)
    with maker() as db:
        db.add_all(
            [
                Template(name="Layout", category="report", content=LAYOUT, description="Two"),
                Template(name="Old", category="report", content=LAYOUT, is_active=False),
                Template(name="Config", category="netmiko", content="hostname {{ x }}"),
            ]
        )
        for source in ("nautobot", "report_data"):
            db.add(
                ReportSnapshot(
                    name=source,
                    status="complete",
                    content={
                        "name": source,
                        "description": None,
                        "sections": [{"section": {"id": "s1", "query": {"source": source}}}],
                    },
                )
            )
        db.commit()
    monkeypatch.setattr(module, "SessionLocal", maker)
    return DbReportReader(7, "report_data")


def run(coro):
    return asyncio.run(coro)


def test_only_active_report_templates_are_listed_with_their_sections(reader) -> None:
    (info,) = run(reader.list_templates())
    assert info["name"] == "Layout"
    assert sorted(info["section_ids"]) == ["devices", "totals"]
    assert "content" not in info  # the template text stays out
    assert "hostname" not in str(info)


def test_get_template_refuses_other_categories_inactive_and_missing(reader) -> None:
    for template_id in (2, 3, 99):
        with pytest.raises(ReportNotFoundError):
            run(reader.get_template(template_id))
    assert run(reader.get_template(1))["id"] == 1


def test_templates_need_the_templates_permission(reader, granted) -> None:
    granted.discard("templates:read")
    with pytest.raises(ReportAccessError):
        run(reader.list_templates())
    with pytest.raises(ReportAccessError):
        run(reader.get_template(1))


def test_reports_permission_guards_sources_and_templates(reader, granted) -> None:
    granted.discard("reports:read")
    for call in (reader.list_sources(), reader.list_templates()):
        with pytest.raises(ReportAccessError):
            run(call)


def test_sources_list_the_report_database_and_nautobot(reader) -> None:
    assert [s["id"] for s in run(reader.list_sources())] == ["report_data", "nautobot"]


def test_a_query_runs_against_its_own_source(reader, monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    class Service:
        def __init__(self, db, **kw):
            pass

        def validate(self, source_id, query):
            seen.append((source_id, query.source))

    monkeypatch.setattr(module, "ReportQueryService", Service)
    run(reader.validate_query(ReportQuery(source="nautobot", dataset="devices")))
    assert seen == [("nautobot", "nautobot")]


def test_a_stored_nautobot_snapshot_needs_the_nautobot_permission(reader, granted) -> None:
    """Review: the stored rows came from sources.nautobot:read; reading them needs it too."""
    with pytest.raises(ReportAccessError):
        run(reader.get_snapshot(1))
    assert run(reader.get_snapshot(2))["name"] == "report_data"  # no source permission needed
    granted.add("sources.nautobot:read")
    assert run(reader.get_snapshot(1))["name"] == "nautobot"
