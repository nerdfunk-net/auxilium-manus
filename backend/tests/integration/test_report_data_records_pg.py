"""Area 3 — ReportDataRecord on real Postgres.

What in-memory SQLite can't prove: run-scoped replacement, the ``ON DELETE SET NULL``
foreign key and latest-collection-per-device on the real dialect. Uses ``clean_tables``
because the repository commits through its own session.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

import core.database as db_mod
from core.models.report_data_records import ReportDataRecord
from core.models.runs import WorkflowRun
from repositories.report_data_records_repository import ReportDataRecordRepository
from tests.integration.helpers.workflows import build_linear_workflow, make_run, node

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


@pytest.fixture
def runs(session, admin_user):
    workflow = build_linear_workflow(
        session, creator_id=admin_user.id, nodes=[node("n1", "show-summary", {})]
    )
    return [make_run(session, workflow=workflow, triggered_by_id=admin_user.id) for _ in range(2)]


def _write(repo, rows, *, device="r1", dataset="inv", run_id=None):
    repo.replace_rows(device_name=device, dataset=dataset, rows=rows, run_id=run_id)


def test_runless_rows_append_and_a_run_replaces_its_own_collection(session, runs) -> None:
    repo = ReportDataRecordRepository(session)
    run_a, run_b = runs

    _write(repo, [{"v": 1}])
    _write(repo, [{"v": 2}])
    _write(repo, [{"v": 3}, {"v": 31}], run_id=run_a.id)
    _write(repo, [{"v": 4}], run_id=run_a.id)
    _write(repo, [{"v": 5}], run_id=run_b.id)

    values = [r.data["v"] for r in session.scalars(select(ReportDataRecord).order_by("id"))]
    assert values == [1, 2, 4, 5]


def test_latest_per_device_returns_the_newest_collection(session, runs) -> None:
    repo = ReportDataRecordRepository(session)
    run_a, run_b = runs
    _write(repo, [{"n": "old1"}, {"n": "old2"}], dataset="ifaces", run_id=run_a.id)
    _write(repo, [{"n": "new1"}], dataset="ifaces", run_id=run_b.id)
    _write(repo, [{"n": "only"}], dataset="ifaces", device="r2", run_id=run_b.id)
    _write(repo, [{"n": "x"}], dataset="other", device="r3")

    latest = repo.latest_per_device("ifaces")

    assert [(r.device_name, r.data["n"]) for r in latest] == [("r1", "new1"), ("r2", "only")]
    history = repo.history(dataset="ifaces", device_name="r1")
    assert [r.data["n"] for r in history] == ["old1", "old2", "new1"]


def test_empty_collection_supersedes_older_items(session, runs) -> None:
    repo = ReportDataRecordRepository(session)
    run_a, run_b = runs
    _write(repo, [{"a": "10.0.0.1"}], dataset="ntp", run_id=run_a.id)
    _write(repo, [], dataset="ntp", run_id=run_b.id)

    assert repo.latest_per_device("ntp") == []


def test_deleting_a_run_keeps_the_report_row(session, runs) -> None:
    repo = ReportDataRecordRepository(session)
    run_a = runs[0]
    (record,) = repo.replace_rows(device_name="r1", dataset="inv", rows=[{"v": 1}], run_id=run_a.id)
    record_id = record.id

    session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_a.id))
    session.commit()
    session.expire_all()

    survivor = session.get(ReportDataRecord, record_id)
    assert survivor is not None
    assert survivor.run_id is None


def test_unique_index_rejects_a_second_writer_of_the_same_run_collection(session, runs) -> None:
    from sqlalchemy.exc import IntegrityError

    repo = ReportDataRecordRepository(session)
    run_a = runs[0]
    _write(repo, [{"v": 1}], run_id=run_a.id)

    session.add(
        ReportDataRecord(
            device_name="r1",
            dataset="inv",
            data={"v": 2},
            collection_id="rival",
            position=0,
            run_id=run_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Runless rows are not constrained.
    _write(repo, [{"v": 3}])
    _write(repo, [{"v": 4}])


def test_include_empty_returns_the_marker(session, runs) -> None:
    repo = ReportDataRecordRepository(session)
    run_a, run_b = runs
    _write(repo, [{"a": "10.0.0.1"}], dataset="ntp", run_id=run_a.id)
    _write(repo, [], dataset="ntp", run_id=run_b.id)

    assert repo.latest_per_device("ntp") == []
    (marker,) = repo.latest_per_device("ntp", include_empty=True)
    assert marker.is_empty and marker.device_name == "r1"
    history = repo.history(dataset="ntp", device_name="r1", include_empty=True)
    assert [r.is_empty for r in history] == [False, True]
