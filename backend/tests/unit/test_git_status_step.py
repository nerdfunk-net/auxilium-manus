"""Tests for the git-status workflow step executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.git_status.executor import execute as git_status

_CLEAN_STATUS = {
    "clean": True,
    "reasons": [],
    "branch": "main",
    "expected_branch": "main",
    "head_commit": "abc",
    "fetched": True,
    "checks": {"uncommitted": True, "untracked": True, "sync": True},
    "ahead_count": 0,
    "behind_count": 0,
    "modified_count": 0,
    "staged_count": 0,
    "untracked_count": 0,
    "modified_files": [],
    "staged_files": [],
    "untracked_files": [],
    "truncated": False,
}
_DIRTY_STATUS = {
    **_CLEAN_STATUS,
    "clean": False,
    "reasons": ["uncommitted_changes", "behind_origin"],
    "modified_count": 2,
    "modified_files": ["a", "b"],
    "behind_count": 3,
}


class GitStatusStepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = {"id": 7, "name": "r", "url": "https://x/r.git", "branch": "main"}
        self.context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "d1": DeviceContext(id="d1", name="lab", hostname="lab", status=DeviceStatus.OK)
            },
        )
        self.git_service = MagicMock()
        self.git_service.get_repo_path.return_value = "/tmp/repo"

    async def _run(self, config, status=None, error=None):
        collect = patch(
            "workflow_steps.git_status.executor.collect_status",
            side_effect=error,
            return_value=status,
        )
        with (
            collect as collect_mock,
            patch(
                "workflow_steps.common.git_workflow_step.load_git_repository",
                return_value=self.repository,
            ),
            patch("service_factory.build_git_service", return_value=self.git_service),
        ):
            outcomes = await git_status(
                config=config,
                context=self.context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        return outcomes, collect_mock

    async def test_clean(self) -> None:
        outcomes, _ = await self._run({"git_repository_id": 7}, _CLEAN_STATUS)
        self.assertEqual([o.name for o in outcomes], ["clean", "dirty"])
        self.assertIn("d1", outcomes[0].context.devices)
        # the untaken branch carries no devices and is marked inactive
        self.assertEqual(outcomes[1].context.devices, {})
        self.assertTrue(outcomes[1].context.metadata["n1.branch_inactive"])
        self.assertNotIn("n1.branch_inactive", outcomes[0].context.metadata)
        meta = outcomes[0].context.metadata["n1.git_operation"]
        self.assertEqual(meta["operation"], "status")
        self.assertTrue(meta["clean"])

    async def test_dirty_reports_reasons_and_summary(self) -> None:
        outcomes, _ = await self._run({"git_repository_id": 7}, _DIRTY_STATUS)
        self.assertEqual(outcomes[0].name, "dirty")
        self.assertEqual(outcomes[1].name, "clean")
        meta = outcomes[0].context.metadata["n1.git_operation"]
        self.assertEqual(meta["reasons"], ["uncommitted_changes", "behind_origin"])
        self.assertEqual(outcomes[0].summary, "dirty: 2 modified, 3 behind")

    async def test_config_toggles_passed_through(self) -> None:
        _, collect = await self._run(
            {
                "git_repository_id": 7,
                "fetch_remote": False,
                "check_untracked": "false",
            },
            _CLEAN_STATUS,
        )
        kwargs = collect.call_args.kwargs
        self.assertFalse(kwargs["fetch"])
        self.assertFalse(kwargs["check_untracked"])
        self.assertTrue(kwargs["check_uncommitted"])
        self.assertTrue(kwargs["check_sync"])

    async def test_missing_repository_id_fails(self) -> None:
        outcomes, collect = await self._run({})
        names = [o.name for o in outcomes]
        self.assertEqual(sorted(names), ["clean", "dirty", "failure"])
        for inactive in (o for o in outcomes if o.name != "failure"):
            self.assertEqual(inactive.context.devices, {})
            self.assertTrue(inactive.context.metadata["n1.branch_inactive"])
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(failure.context.devices["d1"].status, DeviceStatus.FAILED)
        collect.assert_not_called()

    async def test_fetch_error_fails(self) -> None:
        outcomes, _ = await self._run({"git_repository_id": 7}, error=RuntimeError("fetch boom"))
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertIn("fetch boom", failure.context.metadata["n1.git_operation"]["message"])
        self.assertEqual(sorted(o.name for o in outcomes), ["clean", "dirty", "failure"])

    async def test_failure_message_scrubs_url_credentials(self) -> None:
        err = RuntimeError("fatal: unable to access 'https://git:s3cr3t@host/r.git/'")
        outcomes, _ = await self._run({"git_repository_id": 7}, error=err)
        message = outcomes[0].context.metadata["n1.git_operation"]["message"]  # any outcome
        self.assertNotIn("s3cr3t", message)
        self.assertIn("https://***@host/r.git/", message)

    async def test_runs_even_without_devices(self) -> None:
        self.context = self.context.model_copy(update={"devices": {}})
        outcomes, collect = await self._run({"git_repository_id": 7}, _CLEAN_STATUS)
        self.assertEqual(outcomes[0].name, "clean")
        collect.assert_called_once()

    async def test_clean_summary_only_names_enabled_checks(self) -> None:
        status = {
            **_CLEAN_STATUS,
            "checks": {"uncommitted": True, "untracked": False, "sync": False},
        }
        outcomes, _ = await self._run({"git_repository_id": 7}, status)
        self.assertEqual(outcomes[0].summary, "clean: no uncommitted changes")

    async def test_dirty_summary_ignores_counts_of_disabled_checks(self) -> None:
        status = {
            **_DIRTY_STATUS,
            "reasons": ["untracked_files"],
            "checks": {"uncommitted": False, "untracked": True, "sync": False},
            "untracked_count": 4,
            "behind_count": 9,
            "modified_count": 5,
        }
        outcomes, _ = await self._run({"git_repository_id": 7}, status)
        self.assertEqual(outcomes[0].summary, "dirty: 4 untracked")


class GitStepsOnInactiveBranchTests(unittest.IsolatedAsyncioTestCase):
    async def _push(self, context: WorkflowContext):
        from workflow_steps.git_push.executor import execute as git_push

        git_service = MagicMock()
        with (
            patch("workflow_steps.common.git_workflow_step.load_git_repository") as load,
            patch("service_factory.build_git_service", return_value=git_service),
        ):
            outcomes = await git_push(
                config={"git_repository_id": 7},
                context=context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="push-1",
                device_sessions=MagicMock(),
            )
        return outcomes, load, git_service

    async def test_git_push_is_a_noop_on_an_inactive_branch(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={},
            metadata={"status-1.branch_inactive": True},
        )
        outcomes, load, git_service = await self._push(context)
        load.assert_not_called()
        git_service.commit.assert_not_called()
        git_service.push.assert_not_called()
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertTrue(outcomes[0].context.metadata["push-1.git_operation"]["skipped"])

    async def test_git_push_still_runs_on_the_taken_branch(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": DeviceContext(id="d1", name="a", hostname="a", status=DeviceStatus.OK)},
            metadata={"status-1.branch_inactive": True},
        )
        _, load, _ = await self._push(context)
        load.assert_called_once()
