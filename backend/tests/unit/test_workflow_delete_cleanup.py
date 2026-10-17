"""O1-03: deleting a workflow removes the artifacts and log files of its runs.

The database rows go through ON DELETE CASCADE; the files do not, and with retention off they were
never swept. ``delete_run`` already cleaned up after itself, ``delete_workflow`` did not.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models.workflows import Workflow
from services.artifacts.filesystem_artifact_service import FilesystemArtifactService
from services.workflow.workflow_service import WorkflowService


def _write_artifact(data_dir: Path, artifact_id: str, run_id: str) -> None:
    artifacts = data_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / f"{artifact_id}.meta.json").write_text(
        json.dumps({"artifact_id": artifact_id, "run_id": run_id, "kind": "running_config"}),
        encoding="utf-8",
    )
    (artifacts / f"{artifact_id}.content").write_text("hostname r1", encoding="utf-8")


def test_delete_for_runs_removes_only_the_given_runs(tmp_path: Path) -> None:
    for artifact_id, run_id in [("a1", "run-1"), ("a2", "run-2"), ("a3", "run-3")]:
        _write_artifact(tmp_path, artifact_id, run_id)
    service = FilesystemArtifactService(tmp_path)

    deleted = service.delete_for_runs({"run-1", "run-3"})

    assert deleted == 2
    remaining = sorted(p.name for p in (tmp_path / "artifacts").iterdir())
    assert remaining == ["a2.content", "a2.meta.json"]


def test_delete_for_runs_with_no_runs_is_a_noop(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "a1", "run-1")
    assert FilesystemArtifactService(tmp_path).delete_for_runs(set()) == 0
    assert (tmp_path / "artifacts" / "a1.content").exists()


def _service(workflow: Workflow) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = (workflow, "creator")
    return service


def _delete(service: WorkflowService, *, uuids: list[str], artifacts: MagicMock, dirs: MagicMock):
    with (
        patch("services.auth.rbac_service.RBACService.has_role", return_value=True),
        patch("services.workflow.workflow_service.ScheduleService"),
        patch("services.workflow.workflow_service.BackgroundTierService"),
        patch("services.workflow.workflow_service.RunRepository") as run_repo,
        patch("services.workflow.workflow_service.FilesystemArtifactService", artifacts),
        patch("services.workflow.workflow_service.delete_run_dir", dirs),
    ):
        run_repo.return_value.has_active_runs.return_value = False
        run_repo.return_value.list_uuids_for_workflow.return_value = uuids
        service.delete_workflow(5, user_id=2)


def test_delete_workflow_removes_artifacts_and_log_dirs_of_its_runs() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    artifacts, dirs = MagicMock(), MagicMock()

    _delete(service, uuids=["u1", "u2"], artifacts=artifacts, dirs=dirs)

    service.repo.delete.assert_called_once_with(wf)
    artifacts.return_value.delete_for_runs.assert_called_once_with({"u1", "u2"})
    assert sorted(c.args for c in dirs.call_args_list) == [(5, "u1"), (5, "u2")]


def test_delete_workflow_cleans_up_after_the_row_delete_not_before() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    order: list[str] = []
    service.repo.delete.side_effect = lambda _wf: order.append("db")
    artifacts, dirs = MagicMock(), MagicMock()
    artifacts.return_value.delete_for_runs.side_effect = lambda _u: order.append("files")

    _delete(service, uuids=["u1"], artifacts=artifacts, dirs=dirs)

    assert order == ["db", "files"]


def test_a_file_cleanup_failure_does_not_fail_the_delete() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    artifacts, dirs = MagicMock(), MagicMock()
    artifacts.return_value.delete_for_runs.side_effect = OSError("disk")

    _delete(service, uuids=["u1"], artifacts=artifacts, dirs=dirs)  # must not raise

    service.repo.delete.assert_called_once_with(wf)


def test_a_workflow_without_runs_touches_no_files() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    artifacts, dirs = MagicMock(), MagicMock()

    _delete(service, uuids=[], artifacts=artifacts, dirs=dirs)

    artifacts.return_value.delete_for_runs.assert_not_called()
    dirs.assert_not_called()
