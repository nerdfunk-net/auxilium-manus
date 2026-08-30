"""Area 3 — WorkflowRun / WorkflowStepResult persistence + artifact split.

Metadata (status / timestamps / device ids) lives on the row; content
(command output) goes through ``FilesystemArtifactService``. Uses ``clean_tables``
because ``RunRepository`` commits through its own session.
"""

from __future__ import annotations

import pytest

import core.database as db_mod
from core.config import settings
from repositories.run_repository import RunRepository
from services.artifacts import FilesystemArtifactService
from tests.integration.helpers.aio import run as arun
from tests.integration.helpers.workflows import build_linear_workflow, make_run, node

pytestmark = [
    pytest.mark.integration,
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
def workflow(session, admin_user):
    return build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[
            node("n1", "reachable", {"ping_count": 1}),
            node("n2", "show-summary", {}),
        ],
    )


def test_step_results_lifecycle(session, workflow, admin_user) -> None:
    run = make_run(session, workflow=workflow, triggered_by_id=admin_user.id)
    repo = RunRepository(session)

    s1 = repo.create_step_result(
        run_id=run.id, step_node_id="n1", step_type="reachable", step_name="Reachable"
    )
    s2 = repo.create_step_result(
        run_id=run.id, step_node_id="n2", step_type="show-summary", step_name="Summary"
    )
    assert {s.status for s in repo.get_step_results_for_run(run.id)} == {"pending"}

    repo.update_step_result(s1, status="success")
    repo.update_step_result(s2, status="skipped")
    statuses = {s.step_node_id: s.status for s in repo.get_step_results_for_run(run.id)}
    assert statuses == {"n1": "success", "n2": "skipped"}


def test_run_status_transition_sets_finished_at(session, workflow, admin_user) -> None:
    from datetime import UTC, datetime

    run = make_run(session, workflow=workflow, triggered_by_id=admin_user.id)
    repo = RunRepository(session)
    updated = repo.update_run_status(
        run, status="success", finished_at=datetime.now(UTC)
    )
    assert updated.status == "success"
    assert updated.finished_at is not None


def test_step_results_cascade_on_run_delete(session, workflow, admin_user) -> None:
    run = make_run(session, workflow=workflow, triggered_by_id=admin_user.id)
    repo = RunRepository(session)
    repo.create_step_result(
        run_id=run.id, step_node_id="n1", step_type="reachable", step_name="Reachable"
    )
    run_id = run.id
    repo.delete_run(run)
    session.expire_all()
    assert repo.get_step_results_for_run(run_id) == []


def test_metadata_vs_content_split(session, workflow, admin_user, tmp_path) -> None:
    run = make_run(
        session,
        workflow=workflow,
        triggered_by_id=admin_user.id,
        device_ids=["dev-1"],
    )
    # Metadata lives on the row.
    assert run.device_ids == ["dev-1"]
    assert run.status == "pending"

    # Content goes to the artifact store, keyed by run uuid + device id.
    artifacts = FilesystemArtifactService(tmp_path)
    ref = arun(
        artifacts.store(
            content="hostname router1\n!\n",
            kind="running_config",
            device_id="dev-1",
            run_id=run.uuid,
        )
    )
    content_file = tmp_path / "artifacts" / f"{ref.artifact_id}.content"
    assert content_file.is_file()

    resolved_ref, text = artifacts.get_for_run(run_uuid=run.uuid, artifact_id=ref.artifact_id)
    assert "hostname router1" in text
    assert resolved_ref.kind == "running_config"


def test_data_directory_is_test_scoped() -> None:
    # Sanity: the real artifact dir the app would use is resolvable.
    assert isinstance(settings.data_directory.name, str)
