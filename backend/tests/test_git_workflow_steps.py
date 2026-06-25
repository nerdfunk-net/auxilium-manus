"""Tests for git workflow steps."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.git.service import CommitResult, PullResult, PushResult
from workflow_steps.git_clone.executor import execute as git_clone
from workflow_steps.git_pull.executor import execute as git_pull
from workflow_steps.git_push.executor import execute as git_push


class GitWorkflowStepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.run = MagicMock()
        self.run.id = 42
        self.artifact_service = MagicMock()
        self.repository = {
            "id": "prod-configs",
            "name": "prod-configs",
            "source_id": "prod-configs",
            "url": "https://example.com/repo.git",
            "branch": "main",
            "path": "prod-configs",
        }
        self.context = WorkflowContext(
            run_id="run-uuid-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(
                    id="device-1",
                    name="lab",
                    hostname="lab",
                    status=DeviceStatus.OK,
                )
            },
        )

    async def test_git_clone_success(self) -> None:
        git_service = MagicMock()
        git_service.get_repo_path.return_value = MagicMock(__str__=lambda self: "/tmp/repo")

        with patch(
            "workflow_steps.common.git_workflow_step.load_git_source_repository",
            return_value=self.repository,
        ), patch(
            "service_factory.build_git_service",
            return_value=git_service,
        ):
            outcomes = await git_clone(
                config={"git_source_id": "prod-configs"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="git-clone-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        operation = outcomes[0].context.metadata["git-clone-1.git_operation"]
        self.assertTrue(operation["success"])
        self.assertEqual(operation["operation"], "clone")
        git_service.clone.assert_called_once()

    async def test_git_pull_failure_marks_devices(self) -> None:
        git_service = MagicMock()
        git_service.pull.return_value = PullResult(success=False, message="pull failed")
        git_service.get_repo_path.return_value = MagicMock(__str__=lambda self: "/tmp/repo")

        with patch(
            "workflow_steps.common.git_workflow_step.load_git_source_repository",
            return_value=self.repository,
        ), patch(
            "service_factory.build_git_service",
            return_value=git_service,
        ):
            outcomes = await git_pull(
                config={"git_source_id": "prod-configs"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="git-pull-1",
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[1].name, "failure")
        self.assertEqual(outcomes[1].context.devices["device-1"].status, DeviceStatus.FAILED)

    async def test_git_push_commits_exports_before_push(self) -> None:
        git_service = MagicMock()
        repo = MagicMock()
        git_service.open_or_clone.return_value = repo
        repo_path = Path("/tmp/repo")
        git_service.get_repo_path.return_value = repo_path
        git_service.commit.return_value = CommitResult(
            success=True,
            message="committed",
            commit_sha="abc123",
            files_changed=1,
        )
        git_service.push.return_value = PushResult(
            success=True,
            message="pushed",
            pushed=True,
            branch="main",
        )

        context = WorkflowContext(
            run_id="run-uuid-1",
            workflow_id="wf-1",
            metadata={
                "store-artifact-4.stored_artifacts": [
                    {"path": "/tmp/repo/configs/lab.cfg"}
                ]
            },
        )

        with patch(
            "workflow_steps.common.git_workflow_step.load_git_source_repository",
            return_value=self.repository,
        ), patch(
            "service_factory.build_git_service",
            return_value=git_service,
        ):
            outcomes = await git_push(
                config={
                    "git_source_id": "prod-configs",
                    "commit_message_template": "backup {run.id}",
                },
                context=context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="git-push-1",
            )

        self.assertEqual(len(outcomes), 1)
        git_service.commit.assert_called_once()
        commit_kwargs = git_service.commit.call_args.kwargs
        self.assertEqual(commit_kwargs["files"], ["configs/lab.cfg"])
        self.assertEqual(commit_kwargs["message"], "backup run-uuid-1")
        git_service.push.assert_called_once()
        operation = outcomes[0].context.metadata["git-push-1.git_operation"]
        self.assertTrue(operation["committed"])
        self.assertTrue(operation["pushed"])

    async def test_git_push_success_without_devices(self) -> None:
        git_service = MagicMock()
        git_service.open_or_clone.return_value = MagicMock()
        git_service.commit.return_value = CommitResult(
            success=True,
            message="no changes",
            files_changed=0,
        )
        git_service.push.return_value = PushResult(
            success=True,
            message="pushed",
            pushed=True,
            branch="main",
        )
        git_service.get_repo_path.return_value = MagicMock(__str__=lambda self: "/tmp/repo")
        empty_context = WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1")

        with patch(
            "workflow_steps.common.git_workflow_step.load_git_source_repository",
            return_value=self.repository,
        ), patch(
            "service_factory.build_git_service",
            return_value=git_service,
        ):
            outcomes = await git_push(
                config={"git_source_id": "prod-configs"},
                context=empty_context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="git-push-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        operation = outcomes[0].context.metadata["git-push-1.git_operation"]
        self.assertTrue(operation["pushed"])

    async def test_missing_git_source_id_returns_failure(self) -> None:
        outcomes = await git_clone(
            config={"git_source_id": ""},
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1"),
            run=self.run,
            artifact_service=self.artifact_service,
            node_id="git-clone-1",
        )
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[1].name, "failure")


if __name__ == "__main__":
    unittest.main()
