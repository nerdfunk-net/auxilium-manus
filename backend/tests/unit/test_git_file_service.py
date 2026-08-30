"""Tests for services/git/file_service.py against a real throwaway git repo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_repo_builder import make_working_repo
from fastapi import HTTPException
from git import Repo

from core.domain_exceptions import (
    AccessDeniedError,
    NotFoundError,
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
    def test_search_files_lists_all_when_no_query(self) -> None:
        result = self.service.search_files(1)
        self.assertTrue(result["success"])
        names = {f["name"] for f in result["data"]["files"]}
        self.assertIn("README.md", names)
        self.assertIn("router1.cfg", names)

    def test_search_files_applies_query_and_has_more(self) -> None:
        result = self.service.search_files(1, query="router", limit=1)
        self.assertEqual(result["data"]["filtered_count"], 1)
        self.assertFalse(result["data"]["has_more"])

    def test_search_files_missing_repo_returns_empty(self) -> None:
        with patch(
            "services.git.file_service.git_repo_path",
            return_value=Path(self._tmp.name) / "gone",
        ):
            result = self.service.search_files(1)
        self.assertEqual(result["data"]["total_count"], 0)

    def test_search_files_unknown_repo_raises_not_found(self) -> None:
        self.repos.get_repository.return_value = None
        with self.assertRaises(NotFoundError):
            self.service.search_files(1)

    # -- get_commit_files --------------------------------------------------
    def test_get_commit_files_single_file_content(self) -> None:
        head = self.repo.head.commit.hexsha
        out = self.service.get_commit_files(1, head, file_path="config/router1.cfg")
        self.assertIn("hostname router1", out["content"])

    def test_get_commit_files_missing_file_raises_not_found(self) -> None:
        head = self.repo.head.commit.hexsha
        with self.assertRaises(NotFoundError):
            self.service.get_commit_files(1, head, file_path="does/not/exist")

    def test_get_commit_files_lists_config_files_when_no_path(self) -> None:
        head = self.repo.head.commit.hexsha
        # Builder repo holds README.md, config/router1.cfg, data.bin — the binary
        # is filtered out by settings.allowed_file_extensions.
        self.assertEqual(
            self.service.get_commit_files(1, head),
            ["README.md", "config/router1.cfg"],
        )

    def test_get_commit_files_honours_configured_extensions(self) -> None:
        head = self.repo.head.commit.hexsha
        with patch(
            "services.git.file_service.settings.allowed_file_extensions", [".cfg"]
        ):
            self.assertEqual(
                self.service.get_commit_files(1, head), ["config/router1.cfg"]
            )

    # -- get_file_last_commit -------------------------------------------------
    def test_get_file_last_commit_returns_metadata(self) -> None:
        out = self.service.get_file_last_commit(1, "README.md")
        self.assertTrue(out["file_exists"])
        self.assertEqual(out["last_commit"]["message"], "update readme")

    def test_get_file_last_commit_unknown_file_raises(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.get_file_last_commit(1, "nope.txt")

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
    def test_get_file_content_reads_text(self) -> None:
        self.assertIn("second line", self.service.get_file_content(1, "README.md"))

    def test_get_file_content_path_escape_denied(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.get_file_content(1, "../../etc/passwd")

    def test_get_file_content_missing_file(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.get_file_content(1, "absent.cfg")

    def test_get_file_content_directory_is_rejected(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self.service.get_file_content(1, "config")

    def test_get_file_content_binary_rejected(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self.service.get_file_content(1, "data.bin")

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
    def test_get_directory_tree_structure(self) -> None:
        tree = self.service.get_directory_tree(1)
        self.assertEqual(tree["type"], "directory")
        child_names = {c["name"] for c in tree["children"]}
        self.assertIn("config", child_names)

    def test_get_directory_tree_missing_repo_returns_stub(self) -> None:
        with patch(
            "services.git.file_service.git_repo_path",
            return_value=Path(self._tmp.name) / "gone",
        ):
            tree = self.service.get_directory_tree(1)
        self.assertEqual(tree["children"], [])

    def test_get_directory_tree_path_escape_denied(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.get_directory_tree(1, path="../..")

    def test_get_directory_tree_not_a_directory(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self.service.get_directory_tree(1, path="README.md")

    # -- get_directory_files ------------------------------------------
    def test_get_directory_files_lists_entries_with_last_commit(self) -> None:
        out = self.service.get_directory_files(1, path="config")
        self.assertTrue(out["directory_exists"])
        self.assertEqual(out["files"][0]["name"], "router1.cfg")
        self.assertTrue(out["files"][0]["last_commit"]["hash"])

    def test_get_directory_files_missing_dir(self) -> None:
        out = self.service.get_directory_files(1, path="nowhere")
        self.assertFalse(out["directory_exists"])

    def test_raises_http_exception_on_unexpected_error(self) -> None:
        with patch(
            "services.git.file_service.get_git_repo_by_id", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(HTTPException):
                self.service.get_file_last_commit(1, "README.md")


if __name__ == "__main__":
    unittest.main()
