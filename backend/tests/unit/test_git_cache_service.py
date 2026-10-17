"""Tests for services/git/cache.py against a real throwaway git repo + mock cache."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from _git_repo_builder import make_working_repo

from models.git import GitCommit
from services.git.cache import GitCacheService


class GitCacheServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_path = str(make_working_repo(Path(self._tmp.name)))
        self.cache = MagicMock(spec=["get", "set", "delete_pattern"])

    def _service(self) -> GitCacheService:
        return GitCacheService(self.cache)

    def test_build_cache_key(self) -> None:
        svc = self._service()
        self.assertEqual(svc._build_cache_key(7), "repo:7")
        self.assertEqual(svc._build_cache_key(7, "commits", "main"), "repo:7:commits:main")

    def test_get_commits_cache_hit_returns_slice(self) -> None:
        cached = [
            {"hash": f"h{i}", "short_hash": f"h{i}", "message": "m", "date": "d",
             "author": {"name": "n", "email": "e"}, "files_changed": 0}
            for i in range(5)
        ]
        self.cache.get.return_value = cached
        result = self._service().get_commits(1, self.repo_path, "main", limit=2)
        self.assertEqual(len(result), 2)

    def test_get_commits_cache_hit_as_models(self) -> None:
        self.cache.get.return_value = [
            {"hash": "h", "short_hash": "h", "message": "m", "date": "d",
             "author": {"name": "n", "email": "e"}, "files_changed": 0}
        ]
        result = self._service().get_commits(1, self.repo_path, "main", use_models=True)
        self.assertIsInstance(result[0], GitCommit)

    def test_get_commits_cache_miss_reads_repo_and_caches(self) -> None:
        self.cache.get.return_value = None
        result = self._service().get_commits(1, self.repo_path, "main")
        self.assertEqual(len(result), 2)  # two commits in the builder repo
        self.assertTrue(all("hash" in c for c in result))
        self.cache.set.assert_called_once()

    def test_fetch_commits_falls_back_to_subprocess_on_bad_repo(self) -> None:
        self.cache.get.return_value = None
        # A path that exists but is not a git repo -> GitPython raises, subprocess also fails
        result = self._service().get_commits(1, self._tmp.name, "main")
        self.assertEqual(result, [])

    def test_fetch_commits_subprocess_direct(self) -> None:
        commits = self._service()._fetch_commits_subprocess(self.repo_path, "main", 10)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["short_hash"], commits[0]["hash"][:8])

    def test_fetch_commits_subprocess_bad_path_returns_empty(self) -> None:
        self.assertEqual(
            self._service()._fetch_commits_subprocess("/nonexistent/xyz", "main", 10), []
        )

    def test_get_file_history_cache_hit(self) -> None:
        self.cache.get.return_value = [{"hash": "x"}]
        result = self._service().get_file_history(1, self.repo_path, "README.md")
        self.assertEqual(result, [{"hash": "x"}])

    def test_get_file_history_reads_repo_and_marks_change_type(self) -> None:
        self.cache.get.return_value = None
        result = self._service().get_file_history(1, self.repo_path, "config/router1.cfg")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["change_type"], "added")
        self.cache.set.assert_called_once()

    def test_get_file_history_bad_repo_returns_empty(self) -> None:
        self.cache.get.return_value = None
        self.assertEqual(self._service().get_file_history(1, self._tmp.name, "README.md"), [])

    def test_invalidate_repo_uses_delete_pattern(self) -> None:
        self._service().invalidate_repo(3)
        self.cache.delete_pattern.assert_called_once_with("repo:3:*")

    def test_invalidate_repo_without_pattern_support_is_noop(self) -> None:
        cache = MagicMock(spec=["get", "set"])
        GitCacheService(cache).invalidate_repo(3)  # no exception

    def test_invalidate_repo_swallows_errors(self) -> None:
        self.cache.delete_pattern.side_effect = RuntimeError("redis down")
        self._service().invalidate_repo(3)  # no exception


if __name__ == "__main__":
    unittest.main()
