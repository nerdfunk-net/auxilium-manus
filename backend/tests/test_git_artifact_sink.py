"""Tests for git artifact sink."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.artifacts.sinks.git_sink import GitArtifactSink
from services.git.service import CommitResult, PullResult, PushResult


class GitArtifactSinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repo_root = Path(self.temp_dir.name) / "repo"
        self.repo_root.mkdir()

        self.git_service = MagicMock()
        self.mock_repo = MagicMock()
        self.git_service.open_or_clone.return_value = self.mock_repo
        self.git_service.pull.return_value = PullResult(success=True, message="pulled")
        self.git_service.commit.return_value = CommitResult(
            success=True,
            message="committed",
            commit_sha="abc123",
            files_changed=1,
        )
        self.git_service.push.return_value = PushResult(
            success=True,
            message="pushed",
            pushed=True,
            branch="main",
        )

        self.repository = {
            "id": 7,
            "name": "device-configs",
            "url": "https://example.com/configs.git",
            "branch": "main",
            "path": "device-configs",
            "is_active": True,
        }

        patcher = patch(
            "services.artifacts.sinks.git_sink.get_repo_path",
            return_value=self.repo_root,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

        service_patcher = patch(
            "service_factory.build_git_service",
            return_value=self.git_service,
        )
        self.addCleanup(service_patcher.stop)
        service_patcher.start()

    async def test_prepare_pulls_when_enabled(self) -> None:
        sink = GitArtifactSink(self.repository, pull_before_write=True)
        await sink.prepare()
        self.git_service.pull.assert_called_once()

    async def test_prepare_fails_when_pull_fails(self) -> None:
        self.git_service.pull.return_value = PullResult(success=False, message="pull failed")
        sink = GitArtifactSink(self.repository, pull_before_write=True)
        with self.assertRaisesRegex(RuntimeError, "pull failed"):
            await sink.prepare()

    async def test_write_text_creates_nested_file(self) -> None:
        sink = GitArtifactSink(
            self.repository,
            repository_subdirectory="network",
        )
        await sink.prepare()
        export = await sink.write_text(
            relative_path="DC1/device.cfg",
            content="hostname device",
            workflow_id="wf-1",
            run_id="run-1",
        )
        target = self.repo_root / "network" / "DC1" / "device.cfg"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), "hostname device")
        self.assertEqual(export.destination, "git")

    async def test_finalize_commits_and_pushes_written_files(self) -> None:
        sink = GitArtifactSink(
            self.repository,
            commit_after_write=True,
            push_after_write=True,
        )
        await sink.prepare()
        await sink.write_text(
            relative_path="device.cfg",
            content="hostname device",
            workflow_id="wf-1",
            run_id="run-1",
        )
        result = await sink.finalize("commit test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.git_service.commit.assert_called_once()
        self.git_service.push.assert_called_once()

    async def test_finalize_write_only_skips_commit_and_push(self) -> None:
        sink = GitArtifactSink(self.repository)
        await sink.prepare()
        await sink.write_text(
            relative_path="device.cfg",
            content="hostname device",
            workflow_id="wf-1",
            run_id="run-1",
        )
        result = await sink.finalize("commit test")
        self.assertIsNone(result)
        self.git_service.commit.assert_not_called()
        self.git_service.push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
