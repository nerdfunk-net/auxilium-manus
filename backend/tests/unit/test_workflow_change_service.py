"""WorkflowChangeService.record_change: commit_sha is only attached on a
successful git sync, and parent_commit_sha chains from the previously
recorded commit — proving two successive versioned saves link up without any
extra git calls."""

from __future__ import annotations

from unittest.mock import MagicMock

from services.workflow.workflow_change_service import WorkflowChangeService
from services.workflow.workflow_git_service import WorkflowGitSyncResult


def _service_with_mocked_repo() -> WorkflowChangeService:
    service = WorkflowChangeService(MagicMock())
    service.repo = MagicMock()
    return service


def test_record_change_skips_commit_sha_when_git_sync_not_ok() -> None:
    service = _service_with_mocked_repo()
    git_result = WorkflowGitSyncResult(status="skipped", message="not version controlled")

    service.record_change(
        1, action="updated", actor_id=1, actor_username="alice", git_result=git_result
    )

    service.repo.get_latest_commit_sha.assert_not_called()
    service.repo.create.assert_called_once_with(
        workflow_id=1,
        actor_id=1,
        actor_username="alice",
        action="updated",
        commit_sha=None,
        parent_commit_sha=None,
    )


def test_record_change_skips_commit_sha_when_git_result_is_none() -> None:
    service = _service_with_mocked_repo()

    service.record_change(
        1, action="created", actor_id=1, actor_username="alice", git_result=None
    )

    service.repo.create.assert_called_once_with(
        workflow_id=1,
        actor_id=1,
        actor_username="alice",
        action="created",
        commit_sha=None,
        parent_commit_sha=None,
    )


def test_record_change_first_versioned_save_has_no_parent() -> None:
    service = _service_with_mocked_repo()
    service.repo.get_latest_commit_sha.return_value = None
    git_result = WorkflowGitSyncResult(status="ok", commit_sha="c1", pushed=True)

    service.record_change(
        1, action="created", actor_id=1, actor_username="alice", git_result=git_result
    )

    service.repo.create.assert_called_once_with(
        workflow_id=1,
        actor_id=1,
        actor_username="alice",
        action="created",
        commit_sha="c1",
        parent_commit_sha=None,
    )


def test_record_change_chains_parent_commit_sha_from_previous_save() -> None:
    service = _service_with_mocked_repo()
    service.repo.get_latest_commit_sha.return_value = "c1"
    git_result = WorkflowGitSyncResult(status="ok", commit_sha="c2", pushed=True)

    service.record_change(
        1, action="updated", actor_id=1, actor_username="alice", git_result=git_result
    )

    service.repo.create.assert_called_once_with(
        workflow_id=1,
        actor_id=1,
        actor_username="alice",
        action="updated",
        commit_sha="c2",
        parent_commit_sha="c1",
    )
