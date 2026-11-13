"""ReportRunExecutor: token in, ad-hoc snapshot out, as the confirming user."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from core.models.templates import Template
from models.report_definitions import ReportDefinitionCreate, ReportSection
from models.reports import ReportQuery
from services.ai_assistant.report_run_exec import ReportRunExecutor
from services.ai_assistant.report_run_token import InvalidReportTokenError, issue_report_token
from services.reports.report_service import InvalidReportError


@pytest.fixture
def factory():
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
    maker = sessionmaker(bind=engine)
    with maker() as seed:
        seed.add(ReportDataset(dataset="inventory", mode="device", field_names=["location"]))
        seed.add(
            ReportDataRecord(
                device_name="sw1", dataset="inventory", data={"location": "dc1"}, collection_id="c"
            )
        )
        seed.commit()

    @contextmanager
    def session():
        with maker() as db:
            yield db

    return session


def _token(dataset: str = "inventory", user_id: int = 7, **kw) -> str:
    report = ReportDefinitionCreate(
        name="Quick",
        sections=[
            ReportSection(
                id="s1",
                title="Devices",
                query=ReportQuery(
                    dataset=dataset, group_by=["location"], metrics=[{"op": "count"}]
                ),
            )
        ],
        **kw,
    )
    return issue_report_token(user_id=user_id, report=report)[0]


def test_generates_an_adhoc_snapshot_for_the_confirming_user(factory) -> None:
    result = ReportRunExecutor(factory).execute(user_id=7, actor_name="alice", token=_token())

    assert (result.status, result.sections_failed) == ("complete", 0)
    assert result.name.startswith("Quick - ")
    with factory() as db:
        snapshot = db.get(ReportSnapshot, result.snapshot_id)
        assert (snapshot.definition_id, snapshot.generated_by) == (None, "alice")


def test_a_failing_section_gives_a_partial_snapshot(factory) -> None:
    result = ReportRunExecutor(factory).execute(
        user_id=7, actor_name="alice", token=_token(dataset="missing")
    )

    assert (result.status, result.sections_failed) == ("partial", 1)


def test_token_of_another_user_is_refused_and_nothing_is_stored(factory) -> None:
    with pytest.raises(InvalidReportTokenError):
        ReportRunExecutor(factory).execute(user_id=8, actor_name="bob", token=_token(user_id=7))
    with factory() as db:
        assert db.query(ReportSnapshot).count() == 0


def test_an_unusable_template_is_refused(factory) -> None:
    with pytest.raises(InvalidReportError):
        ReportRunExecutor(factory).execute(
            user_id=7, actor_name="alice", token=_token(template_id=99)
        )
