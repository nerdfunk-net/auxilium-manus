"""Tests for services/git/version_control_service.py against a real git repo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_repo_builder import git, make_working_repo
from git import Repo

from services.git.version_control_service import GitVersionControlService


class GitVersionControlServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = make_working_repo(Path(self._tmp.name))
        git("branch", "feature", cwd=self.repo_dir)
        self.repo = Repo(self.repo_dir)

        p = patch(
            "services.git.version_control_service.get_git_repo_by_id",
            return_value=self.repo,
        )
        self.addCleanup(p.stop)
        p.start()
        self.service = GitVersionControlService()

    def test_get_branches_flags_current(self) -> None:
        branches = self.service.get_branches(1)
        by_name = {b["name"]: b["current"] for b in branches}
        self.assertTrue(by_name["main"])
        self.assertFalse(by_name["feature"])

    def test_get_commits_unknown_branch_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.service.get_commits(1, "no-such-branch")

    def test_get_commits_returns_list_and_writes_cache(self) -> None:
        cache = MagicMock()
        cache.get.return_value = None
        commits = self.service.get_commits(1, "main", cache_service=cache)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["short_hash"], commits[0]["hash"][:8])
        cache.set.assert_called_once()

    def test_get_commits_cache_hit(self) -> None:
        cache = MagicMock()
        cache.get.return_value = [{"hash": "cached"}]
        self.assertEqual(
            self.service.get_commits(1, "main", cache_service=cache), [{"hash": "cached"}]
        )

    def test_compare_commits_reports_diff_and_sides(self) -> None:
        head = self.repo.head.commit
        parent = head.parents[0]
        result = self.service.compare_commits(
            1, parent.hexsha, head.hexsha, "README.md"
        )
        self.assertEqual(result["file_path"], "README.md")
        self.assertGreaterEqual(result["stats"]["additions"], 1)
        self.assertTrue(any(ln["type"] == "insert" for ln in result["right_lines"]))

    def test_compare_commits_missing_file_yields_empty_sides(self) -> None:
        head = self.repo.head.commit
        result = self.service.compare_commits(
            1, head.hexsha, head.hexsha, "not/here.cfg"
        )
        self.assertEqual(result["stats"]["changes"], 0)
        self.assertEqual(result["left_lines"], [])


if __name__ == "__main__":
    unittest.main()
