"""Tests for services/git/operations.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_repo_builder import make_working_repo
from git import GitCommandError

from core.domain_exceptions import NotFoundError
from core.safe_urls import UnsafeURLError
from services.git.operations import (
    GitOperationsService,
    SyncExecutionError,
    _backup_non_git_directory,
    _empty_repository_status,
    _map_clone_error_message,
    _scan_config_files,
    _sync_needs_clone,
)

_REPO = {
    "id": 1,
    "name": "ops",
    "url": "https://example.com/ops.git",
    "branch": "main",
    "is_active": True,
    "category": "device_configs",
}


class PureHelperTests(unittest.TestCase):
    def test_empty_repository_status_shape(self) -> None:
        status = _empty_repository_status(_REPO, "/tmp/x")
        self.assertEqual(status["repository_name"], "ops")
        self.assertFalse(status["is_git_repo"])

    def test_map_clone_error_message_variants(self) -> None:
        auth_msg = _map_clone_error_message("fatal: Authentication failed", _REPO)
        self.assertIn("Authentication", auth_msg)
        self.assertIn("not found", _map_clone_error_message("repository not found", _REPO).lower())
        self.assertIn("Git clone failed", _map_clone_error_message("some other error", _REPO))

    def test_sync_needs_clone(self) -> None:
        self.assertTrue(_sync_needs_clone(force_clone=True, is_git_repo=True))
        self.assertTrue(_sync_needs_clone(force_clone=False, is_git_repo=False))
        self.assertFalse(_sync_needs_clone(force_clone=False, is_git_repo=True))

    def test_scan_config_files_skips_git_and_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.cfg").write_text("x")
            (root / ".hidden").write_text("x")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref")
            (root / "sub").mkdir()
            (root / "sub" / "b.cfg").write_text("x")
            found = _scan_config_files(str(root))
        self.assertEqual(found, ["a.cfg", "sub/b.cfg"])

    def test_backup_non_git_directory_moves_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "repo"
            target.mkdir()
            (target / "keep.txt").write_text("data")
            _backup_non_git_directory(str(target), repo_dir_exists=True, is_git_repo=False)
            self.assertFalse(target.exists())
            backups = list(Path(tmp).glob("repo_backup_*"))
            self.assertEqual(len(backups), 1)


class GitOperationsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_path = Path(self._tmp.name) / "checkout"

        self.git_service = MagicMock()
        self.repos = MagicMock()
        self.service = GitOperationsService(repos=self.repos)
        self.service._git_service = self.git_service

        p = patch(
            "services.git.operations.get_repo_path", return_value=self.repo_path
        )
        self.addCleanup(p.stop)
        p.start()

    def test_sync_repository_clones_when_no_checkout(self) -> None:
        self.git_service.clone.return_value = MagicMock()
        result = self.service.sync_repository(_REPO)
        self.assertTrue(result.success)
        self.git_service.clone.assert_called_once()

    def test_sync_repository_unsafe_url(self) -> None:
        self.git_service.clone.side_effect = UnsafeURLError("bad")
        result = self.service.sync_repository(_REPO)
        self.assertFalse(result.success)
        self.assertIn("not allowed", result.message)

    def test_sync_repository_git_command_error(self) -> None:
        self.git_service.clone.side_effect = GitCommandError("clone", 128)
        result = self.service.sync_repository(_REPO)
        self.assertFalse(result.success)

    def test_sync_repository_unexpected_error(self) -> None:
        self.git_service.clone.side_effect = RuntimeError("kaboom")
        result = self.service.sync_repository(_REPO)
        self.assertFalse(result.success)
        self.assertIn("Unexpected error", result.message)

    def test_sync_repository_pulls_existing_checkout(self) -> None:
        (self.repo_path / ".git").mkdir(parents=True)
        self.git_service.pull.return_value = MagicMock(success=True, message="pulled 0")
        result = self.service.sync_repository(_REPO)
        self.assertTrue(result.success)
        self.git_service.pull.assert_called_once()

    def test_remove_and_sync_success_and_failure(self) -> None:
        self.git_service.clone.return_value = MagicMock()
        self.assertTrue(self.service.remove_and_sync(_REPO).success)

        self.git_service.clone.side_effect = UnsafeURLError("bad")
        self.assertFalse(self.service.remove_and_sync(_REPO).success)

    def test_get_status_payload_not_found(self) -> None:
        self.repos.get_repository.return_value = None
        with self.assertRaises(NotFoundError):
            self.service.get_status_payload(1)

    def test_get_repository_status_for_real_repo(self) -> None:
        real = make_working_repo(Path(self._tmp.name), name="checkout")
        with patch("service_factory.build_git_cache_service") as cache_factory:
            cache_factory.return_value.get_commits.return_value = []
            status = self.service.get_repository_status(_REPO, 1)
        self.assertTrue(status["is_git_repo"])
        self.assertEqual(status["current_branch"], "main")
        self.assertIn("README.md", status["config_files"])
        assert real  # constructed at checkout path

    def test_sync_and_record_success_updates_status_and_cache(self) -> None:
        self.repos.get_repository.return_value = dict(_REPO)
        self.git_service.clone.return_value = MagicMock()
        cache = MagicMock()
        out = self.service.sync_and_record(1, cache)
        self.assertTrue(out["success"])
        cache.invalidate_repo.assert_called_once_with(1)
        self.repos.update_sync_status.assert_any_call(1, "synced")

    def test_sync_and_record_failure_raises_sync_execution_error(self) -> None:
        self.repos.get_repository.return_value = dict(_REPO)
        self.git_service.clone.side_effect = GitCommandError("clone", 128)
        with self.assertRaises(SyncExecutionError):
            self.service.sync_and_record(1, MagicMock())

    def test_remove_and_sync_and_record_missing_repo(self) -> None:
        self.repos.get_repository.return_value = None
        with self.assertRaises(NotFoundError):
            self.service.remove_and_sync_and_record(1, MagicMock())

    def test_get_info_payload(self) -> None:
        self.repos.get_repository.return_value = dict(_REPO)
        fake_repo = MagicMock()
        fake_repo.iter_commits.return_value = iter([MagicMock(), MagicMock()])
        fake_repo.branches = [MagicMock()]
        fake_repo.active_branch.name = "main"
        fake_repo.working_dir = "/tmp/x"
        with patch(
            "services.git.operations.get_git_repo_by_id", return_value=fake_repo
        ):
            out = self.service.get_info_payload(1)
        self.assertEqual(out["git_stats"]["total_commits"], 2)
        self.assertEqual(out["git_stats"]["current_branch"], "main")

    def test_get_debug_payload(self) -> None:
        fake_repo = MagicMock()
        fake_repo.working_dir = "/tmp/x"
        fake_repo.active_branch.name = "main"
        with patch(
            "services.git.operations.get_git_repo_by_id", return_value=fake_repo
        ):
            out = self.service.get_debug_payload(1)
        self.assertEqual(out["branch"], "main")


if __name__ == "__main__":
    unittest.main()
