"""Tests for services/git/file_service.py against a real throwaway git repo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_repo_builder import make_working_repo
from git import Repo

from core.domain_exceptions import (
    ValidationFailedError,
)
from services.git.file_service import (
    GitFileService,
    _change_type_for_file_at_commit,
    _filter_files_by_query,
    _sort_files_for_search,
)

_REPO_DICT = {"id": 1, "name": "work", "is_active": True, "branch": "main"}


class PureHelperTests(unittest.TestCase):
    def test_filter_files_by_query_matches_name_and_glob(self) -> None:
        files = [
            {"name": "router1.cfg", "path": "config/router1.cfg", "directory": "config"},
            {"name": "notes.txt", "path": "notes.txt", "directory": ""},
        ]
        self.assertEqual(len(_filter_files_by_query(files, "router")), 1)
        self.assertEqual(_filter_files_by_query(files, ""), files)

    def test_sort_files_for_search_ranks_exact_then_prefix(self) -> None:
        files = [
            {"name": "zzz-router.cfg", "path": "z"},
            {"name": "router", "path": "a"},
            {"name": "router-2.cfg", "path": "b"},
        ]
        _sort_files_for_search(files, "router")
        self.assertEqual(files[0]["name"], "router")

    def test_change_type_for_file_at_commit(self) -> None:
        commit = MagicMock()
        commit.tree.__getitem__ = MagicMock(side_effect=KeyError)
        self.assertEqual(_change_type_for_file_at_commit(commit, "x", is_oldest=True), "A")
        self.assertEqual(_change_type_for_file_at_commit(commit, "x", is_oldest=False), "D")


class GitFileServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = make_working_repo(Path(self._tmp.name))
        self.repo = Repo(self.repo_dir)

        self.repos = MagicMock()
        self.repos.get_repository.return_value = dict(_REPO_DICT)

        path_patch = patch(
            "services.git.file_service.git_repo_path", return_value=self.repo_dir
        )
        self.addCleanup(path_patch.stop)
        path_patch.start()

        repo_patch = patch(
            "services.git.file_service.get_git_repo_by_id", return_value=self.repo
        )
        self.addCleanup(repo_patch.stop)
        repo_patch.start()

        self.service = GitFileService(self.repos)

    # -- search_files --------------------------------------------------------
    # -- get_commit_files --------------------------------------------------
    # -- get_file_last_commit -------------------------------------------------
    # -- get_file_history --------------------------------------------------
    def test_get_file_history_full_chain(self) -> None:
        out = self.service.get_file_history(1, "README.md")
        self.assertEqual(out["total_commits"], 2)
        self.assertEqual(out["commits"][-1]["change_type"], "A")

    def test_get_file_history_uses_cache(self) -> None:
        cache = MagicMock()
        cache.get.return_value = {"cached": True}
        out = self.service.get_file_history(1, "README.md", cache_service=cache)
        self.assertEqual(out, {"cached": True})

    def test_get_file_history_writes_cache_on_miss(self) -> None:
        cache = MagicMock()
        cache.get.return_value = None
        self.service.get_file_history(1, "README.md", cache_service=cache)
        cache.set.assert_called_once()

    # -- get_file_content -------------------------------------------------
    # -- get_file_content_parsed ----------------------------------------
    def test_get_file_content_parsed_yaml(self) -> None:
        (self.repo_dir / "meta.yaml").write_text("key: value\nlist:\n  - a\n")
        out = self.service.get_file_content_parsed(1, "meta.yaml")
        self.assertEqual(out["parsed"], {"key": "value", "list": ["a"]})

    def test_get_file_content_parsed_invalid_yaml(self) -> None:
        (self.repo_dir / "bad.yaml").write_text("key: : :\n  - broken\n::")
        with self.assertRaises(ValidationFailedError):
            self.service.get_file_content_parsed(1, "bad.yaml")

    # -- get_directory_tree --------------------------------------------
    # -- get_directory_files ------------------------------------------
if __name__ == "__main__":
    unittest.main()
