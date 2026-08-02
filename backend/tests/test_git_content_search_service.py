"""Tests for GitContentSearchService (current-tree + history text search)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from git import Repo

from services.sources.git.git_content_search_service import (
    MAX_CONTENT_SEARCH_FILE_SIZE,
    GitContentSearchService,
)


class GitContentSearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # realpath() so macOS's /var -> /private/var symlink doesn't trip
        # GitPython's plain-string containment check on the working tree dir.
        self.repo_dir = Path(os.path.realpath(self._tmp.name))
        self.repo = Repo.init(self.repo_dir)
        with self.repo.config_writer() as cfg:
            cfg.set_value("user", "name", "Test")
            cfg.set_value("user", "email", "test@example.com")
        self.service = GitContentSearchService()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _commit(self, rel_path: str, content: str, message: str) -> None:
        path = self.repo_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.repo.index.add([str(path)])
        self.repo.index.commit(message)

    def test_finds_match_in_current_tree(self) -> None:
        self._commit(
            "configs/router1.cfg",
            "hostname router1\n! marker FINDME\n",
            "add router1",
        )

        matches, files_scanned = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="FINDME",
            case_sensitive=False,
        )

        self.assertEqual(files_scanned, 1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].file_path, "configs/router1.cfg")
        self.assertIsNone(matches[0].commit)
        self.assertIn("FINDME", matches[0].line_content)

    def test_case_insensitive_by_default(self) -> None:
        self._commit("router2.cfg", "hostname router2\n! findme lower\n", "add router2")

        matches, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="FINDME",
            case_sensitive=False,
        )
        self.assertEqual(len(matches), 1)

        matches_cs, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="FINDME",
            case_sensitive=True,
        )
        self.assertEqual(len(matches_cs), 0)

    def test_recursive_toggle(self) -> None:
        self._commit("sub/dir/router3.cfg", "hostname router3\n! DEEP\n", "add router3")

        matches_recursive, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="DEEP",
            case_sensitive=False,
        )
        self.assertEqual(len(matches_recursive), 1)

        matches_flat, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=False,
            include_history=False,
            search_text="DEEP",
            case_sensitive=False,
        )
        self.assertEqual(len(matches_flat), 0)

    def test_file_filter_restricts_matches(self) -> None:
        self._commit("router4.cfg", "hostname router4\n! WANTED\n", "add cfg")
        self._commit("notes.txt", "unrelated WANTED text\n", "add txt")

        matches, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="*.cfg",
            recursive=True,
            include_history=False,
            search_text="WANTED",
            case_sensitive=False,
        )

        self.assertEqual([m.file_path for m in matches], ["router4.cfg"])

    def test_directory_scopes_search(self) -> None:
        self._commit("site-a/router5.cfg", "hostname router5\n! SCOPED\n", "site-a")
        self._commit("site-b/router6.cfg", "hostname router6\n! SCOPED\n", "site-b")

        matches, _ = self.service.search(
            self.repo_dir,
            {},
            directory="site-a",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="SCOPED",
            case_sensitive=False,
        )

        self.assertEqual([m.file_path for m in matches], ["site-a/router5.cfg"])

    def test_history_fallback_finds_removed_text(self) -> None:
        self._commit(
            "router7.cfg",
            "hostname router7\n! HISTORICAL_MARKER\n",
            "add with marker",
        )
        self._commit("router7.cfg", "hostname router7\n! marker removed\n", "remove marker")

        matches_no_history, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="HISTORICAL_MARKER",
            case_sensitive=False,
        )
        self.assertEqual(len(matches_no_history), 0)

        matches_history, _ = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=True,
            search_text="HISTORICAL_MARKER",
            case_sensitive=False,
        )
        self.assertEqual(len(matches_history), 1)
        self.assertEqual(matches_history[0].file_path, "router7.cfg")
        self.assertIsNotNone(matches_history[0].commit)
        self.assertIn("HISTORICAL_MARKER", matches_history[0].content)

    def test_skips_oversized_file(self) -> None:
        huge_content = "hostname router8\n" + ("A" * (MAX_CONTENT_SEARCH_FILE_SIZE + 10))
        self._commit("router8.cfg", huge_content, "add huge file")

        matches, files_scanned = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="hostname",
            case_sensitive=False,
        )
        self.assertEqual(files_scanned, 0)
        self.assertEqual(matches, [])

    def test_skips_binary_file(self) -> None:
        binary_path = self.repo_dir / "router9.bin"
        binary_path.write_bytes(b"\xff\xfe\x00\x01hostname\x00")
        self.repo.index.add([str(binary_path)])
        self.repo.index.commit("add binary")

        matches, files_scanned = self.service.search(
            self.repo_dir,
            {},
            directory="",
            file_filter="",
            recursive=True,
            include_history=False,
            search_text="hostname",
            case_sensitive=False,
        )
        self.assertEqual(files_scanned, 1)
        self.assertEqual(matches, [])

    def test_empty_search_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.service.search(
                self.repo_dir,
                {},
                directory="",
                file_filter="",
                recursive=True,
                include_history=False,
                search_text="   ",
                case_sensitive=False,
            )

    def test_directory_escape_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.search(
                self.repo_dir,
                {},
                directory="../../etc",
                file_filter="",
                recursive=True,
                include_history=False,
                search_text="root",
                case_sensitive=False,
            )


if __name__ == "__main__":
    unittest.main()
