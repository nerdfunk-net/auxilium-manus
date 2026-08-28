"""WorkflowGitService: best-effort commit/push of version-controlled workflows.

Modeled on tests/unit/test_git_artifact_sink.py's MagicMock-the-GitService
approach — these tests never touch a real repository or filesystem beyond a
throwaway temp dir.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.git.service import CommitResult, PushResult
from services.workflow.workflow_git_service import WorkflowGitService


def _make_workflow(*, is_version_controlled: bool = True) -> MagicMock:
    workflow = MagicMock()
    workflow.id = 1
    workflow.uuid = "11111111-1111-1111-1111-111111111111"
    workflow.name = "Test Workflow"
    workflow.description = None
    workflow.folder = "/"
    workflow.visibility = "private"
    workflow.canvas_nodes = [{"id": "a"}]
    workflow.canvas_edges = []
    workflow.canvas_groups = []
    workflow.static_attributes = []
    workflow.is_version_controlled = is_version_controlled
    return workflow


class WorkflowGitServiceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repo_root = Path(self.temp_dir.name) / "repo"
        self.repo_root.mkdir()

        self.git_service = MagicMock()
        self.git_service.get_repo_path.return_value = self.repo_root
        self.git_service.open_or_clone.return_value = MagicMock()
        self.git_service.commit.return_value = CommitResult(
            success=True, message="committed", commit_sha="abc123", files_changed=1
        )
        self.git_service.push.return_value = PushResult(
            success=True, message="pushed", pushed=True, branch="main"
        )

        build_patcher = patch("service_factory.build_git_service", return_value=self.git_service)
        self.addCleanup(build_patcher.stop)
        build_patcher.start()
        patch("service_factory.build_git_file_service", return_value=MagicMock()).start()
        self.addCleanup(patch.stopall)
        patch(
            "service_factory.build_git_version_control_service", return_value=MagicMock()
        ).start()

        self.repository = {"id": 42, "name": "workflows-repo", "category": "workflows"}
        self.repos_patcher = patch.object(
            WorkflowGitService,
            "get_configured_repository",
            return_value=self.repository,
        )
        self.repos_patcher.start()
        self.addCleanup(self.repos_patcher.stop)

        self.service = WorkflowGitService(MagicMock())

    def test_skips_when_not_version_controlled(self) -> None:
        workflow = _make_workflow(is_version_controlled=False)
        result = self.service.sync_workflow_to_git(workflow, action="update")
        self.assertEqual(result.status, "skipped")
        self.git_service.open_or_clone.assert_not_called()

    def test_skips_when_no_repository_configured(self) -> None:
        with patch.object(WorkflowGitService, "get_configured_repository", return_value=None):
            workflow = _make_workflow()
            result = self.service.sync_workflow_to_git(workflow, action="update")
        self.assertEqual(result.status, "skipped")
        self.git_service.open_or_clone.assert_not_called()

    def test_happy_path_writes_commits_and_pushes(self) -> None:
        workflow = _make_workflow()
        result = self.service.sync_workflow_to_git(
            workflow, action="update", actor_username="alice"
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.commit_sha, "abc123")
        self.assertTrue(result.pushed)

        written = self.repo_root / "workflows" / f"{workflow.uuid}.json"
        self.assertTrue(written.is_file())
        payload = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(payload["name"], "Test Workflow")
        self.assertNotIn("id", payload)
        self.assertNotIn("creator_id", payload)
        self.assertNotIn("created_at", payload)
        self.assertNotIn("updated_at", payload)

        commit_kwargs = self.git_service.commit.call_args.kwargs
        self.assertIn("by alice", commit_kwargs["message"])
        self.git_service.push.assert_called_once()

    def test_returns_failed_status_when_commit_fails(self) -> None:
        self.git_service.commit.return_value = CommitResult(success=False, message="commit failed")
        workflow = _make_workflow()
        result = self.service.sync_workflow_to_git(workflow, action="update")
        self.assertEqual(result.status, "failed")
        self.git_service.push.assert_not_called()

    def test_returns_failed_status_on_unexpected_exception(self) -> None:
        self.git_service.open_or_clone.side_effect = RuntimeError("boom")
        workflow = _make_workflow()
        result = self.service.sync_workflow_to_git(workflow, action="update")
        self.assertEqual(result.status, "failed")
        self.assertIn("boom", result.message or "")


class WorkflowGitServiceRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        patch("service_factory.build_git_service", return_value=MagicMock()).start()
        patch("service_factory.build_git_file_service", return_value=MagicMock()).start()
        patch(
            "service_factory.build_git_version_control_service", return_value=MagicMock()
        ).start()
        self.addCleanup(patch.stopall)

        self.repository = {"id": 42, "name": "workflows-repo", "category": "workflows"}
        patch.object(
            WorkflowGitService, "get_configured_repository", return_value=self.repository
        ).start()

        self.service = WorkflowGitService(MagicMock())

    def test_restore_builds_workflow_update_from_historical_content(self) -> None:
        workflow = _make_workflow()
        historical = {
            "name": "Renamed Later Back",
            "description": "old description",
            "folder": "/",
            "visibility": "private",
            "canvas_nodes": [{"id": "old-node"}],
            "canvas_edges": [],
            "canvas_groups": [],
            "static_attributes": [],
        }
        blob = MagicMock()
        blob.data_stream.read.return_value = json.dumps(historical).encode("utf-8")
        commit = MagicMock()
        commit.tree.__truediv__.return_value = blob
        repo = MagicMock()
        repo.commit.return_value = commit

        with patch(
            "services.workflow.workflow_git_service.get_git_repo_by_id", return_value=repo
        ):
            update = self.service.restore_version(workflow, "deadbeef")

        self.assertEqual(update.name, "Renamed Later Back")
        self.assertEqual(update.canvas_nodes, [{"id": "old-node"}])


if __name__ == "__main__":
    unittest.main()
