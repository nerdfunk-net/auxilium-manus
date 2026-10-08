"""Tests for services.git.working_tree_status.collect_status (real throwaway repos)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from git import Repo

from services.git.service import GitResult
from services.git.working_tree_status import collect_status
from tests.unit._git_repo_builder import git, make_working_repo


class CollectStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        # origin (bare) <- seed work repo pushed -> local clone under test
        self.origin = root / "origin.git"
        git("init", "--bare", "-b", "main", str(self.origin), cwd=root)
        seed = make_working_repo(root, "seed")
        git("remote", "add", "origin", str(self.origin), cwd=seed)
        git("push", "-u", "origin", "main", cwd=seed)
        self.seed = seed
        self.local = root / "local"
        git("clone", str(self.origin), str(self.local), cwd=root)
        git("config", "user.email", "committer@test.local", cwd=self.local)
        git("config", "user.name", "Test Committer", cwd=self.local)
        self.repository = {"name": "r", "url": "x", "branch": "main"}
        self.git_service = MagicMock()
        self.git_service.open_or_clone.return_value = Repo(self.local)
        self.git_service.fetch.return_value = GitResult(success=True, message="ok")

    def _status(self, **kwargs):
        return collect_status(self.git_service, self.repository, fetch=False, **kwargs)

    def test_clean_repo(self) -> None:
        result = self._status()
        self.assertTrue(result["clean"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["ahead_count"], 0)
        self.assertEqual(result["behind_count"], 0)
        self.assertEqual(result["branch"], "main")

    def test_modified_file(self) -> None:
        (self.local / "README.md").write_text("changed\n")
        result = self._status()
        self.assertFalse(result["clean"])
        self.assertIn("uncommitted_changes", result["reasons"])
        self.assertIn("README.md", result["modified_files"])

    def test_staged_file(self) -> None:
        (self.local / "new.txt").write_text("x\n")
        git("add", "new.txt", cwd=self.local)
        result = self._status()
        self.assertIn("uncommitted_changes", result["reasons"])
        self.assertIn("new.txt", result["staged_files"])

    def test_untracked_file(self) -> None:
        (self.local / "stray.txt").write_text("x\n")
        result = self._status()
        self.assertEqual(result["reasons"], ["untracked_files"])
        self.assertEqual(result["untracked_files"], ["stray.txt"])

    def test_ahead_of_origin(self) -> None:
        (self.local / "a.txt").write_text("a\n")
        git("add", "-A", cwd=self.local)
        git("commit", "-m", "local", cwd=self.local)
        result = self._status()
        self.assertEqual(result["reasons"], ["ahead_of_origin"])
        self.assertEqual(result["ahead_count"], 1)

    def test_behind_origin(self) -> None:
        (self.seed / "b.txt").write_text("b\n")
        git("add", "-A", cwd=self.seed)
        git("commit", "-m", "upstream", cwd=self.seed)
        git("push", "origin", "main", cwd=self.seed)
        git("fetch", "origin", cwd=self.local)
        result = self._status()
        self.assertEqual(result["reasons"], ["behind_origin"])
        self.assertEqual(result["behind_count"], 1)

    def test_fetch_called_when_enabled(self) -> None:
        collect_status(self.git_service, self.repository, fetch=True)
        self.git_service.fetch.assert_called_once()

    def test_fetch_failure_raises(self) -> None:
        self.git_service.fetch.return_value = GitResult(success=False, message="boom")
        with self.assertRaises(RuntimeError):
            collect_status(self.git_service, self.repository, fetch=True)

    def test_branch_mismatch(self) -> None:
        git("checkout", "-b", "feature", cwd=self.local)
        result = self._status()
        self.assertIn("branch_mismatch", result["reasons"])
        self.assertEqual(result["branch"], "feature")

    def test_detached_head_is_branch_mismatch(self) -> None:
        git("checkout", "--detach", cwd=self.local)
        result = self._status()
        self.assertIn("branch_mismatch", result["reasons"])

    def test_no_remote_branch(self) -> None:
        self.repository = {**self.repository, "branch": "missing"}
        git("checkout", "-b", "missing", cwd=self.local)
        result = self._status()
        self.assertIn("no_remote_branch", result["reasons"])

    def test_toggles_ignore_conditions(self) -> None:
        (self.local / "stray.txt").write_text("x\n")
        (self.local / "README.md").write_text("changed\n")
        result = self._status(check_uncommitted=False, check_untracked=False)
        self.assertTrue(result["clean"])

    def test_file_lists_are_capped(self) -> None:
        for i in range(105):
            (self.local / f"f{i}.txt").write_text("x\n")
        result = self._status()
        self.assertEqual(len(result["untracked_files"]), 100)
        self.assertEqual(result["untracked_count"], 105)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
