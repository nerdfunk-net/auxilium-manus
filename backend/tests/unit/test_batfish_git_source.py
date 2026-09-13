"""Tests for workflow_steps.batfish_init_snapshot.git_source."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_steps.batfish_init_snapshot.git_source import (
    collect_git_source_files,
    copy_git_source_files_into,
)


class GitSourceFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name)

    def _write(self, relative_path: str, content: str = "hostname R1\n") -> Path:
        path = self.repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_suffix_glob_matches_expected_files(self) -> None:
        self._write("r1.running.cfg")
        self._write("r2.running.cfg")
        self._write("r1.startup.cfg")
        self._write("readme.md")

        matches = collect_git_source_files(
            repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
        )

        names = sorted(p.name for p in matches)
        self.assertEqual(names, ["r1.running.cfg", "r2.running.cfg"])

    def test_directory_glob_matches_expected_files(self) -> None:
        self._write("configs/running/r1.cfg")
        self._write("configs/running/r2.cfg")
        self._write("configs/startup/r1.cfg")

        matches = collect_git_source_files(
            repo_root=self.repo_root, base_path="", glob_pattern="configs/running/**/*.cfg"
        )

        rels = sorted(str(p.relative_to(self.repo_root.resolve())) for p in matches)
        self.assertEqual(rels, ["configs/running/r1.cfg", "configs/running/r2.cfg"])

    def test_base_path_scopes_the_search(self) -> None:
        self._write("configs/running/r1.cfg")
        self._write("other/r2.cfg")

        matches = collect_git_source_files(
            repo_root=self.repo_root, base_path="configs/running", glob_pattern="*.cfg"
        )

        self.assertEqual([p.name for p in matches], ["r1.cfg"])

    def test_git_directory_is_skipped(self) -> None:
        self._write(".git/objects/r1.running.cfg")
        self._write("r2.running.cfg")

        matches = collect_git_source_files(
            repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
        )

        self.assertEqual([p.name for p in matches], ["r2.running.cfg"])

    def test_symlink_escaping_repo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_file = Path(outside_dir) / "outside.running.cfg"
            outside_file.write_text("hostname OUTSIDE\n", encoding="utf-8")

            link = self.repo_root / "escape.running.cfg"
            try:
                os.symlink(outside_file, link)
            except OSError:
                self.skipTest("symlinks not supported in this environment")

            self._write("r1.running.cfg")

            matches = collect_git_source_files(
                repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
            )

            self.assertEqual([p.name for p in matches], ["r1.running.cfg"])

    def test_base_path_escape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            collect_git_source_files(
                repo_root=self.repo_root, base_path="../outside", glob_pattern="*.cfg"
            )

    def test_missing_base_path_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            collect_git_source_files(
                repo_root=self.repo_root, base_path="does/not/exist", glob_pattern="*.cfg"
            )

    def test_no_matches_raises_value_error(self) -> None:
        self._write("r1.startup.cfg")
        with self.assertRaises(ValueError):
            collect_git_source_files(
                repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
            )

    def test_empty_glob_pattern_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            collect_git_source_files(repo_root=self.repo_root, base_path="", glob_pattern="   ")

    def test_file_count_cap_raises_value_error(self) -> None:
        self._write("r1.running.cfg")
        self._write("r2.running.cfg")
        self._write("r3.running.cfg")

        with patch(
            "workflow_steps.batfish_init_snapshot.git_source.MAX_GIT_SOURCE_FILES", 2
        ):
            with self.assertRaises(ValueError):
                collect_git_source_files(
                    repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
                )

    def test_file_size_cap_skips_oversized_file(self) -> None:
        self._write("r1.running.cfg", content="x" * 100)
        self._write("r2.running.cfg", content="y" * 10)

        with patch(
            "workflow_steps.batfish_init_snapshot.git_source.MAX_GIT_SOURCE_FILE_SIZE", 50
        ):
            matches = collect_git_source_files(
                repo_root=self.repo_root, base_path="", glob_pattern="**/*.running.cfg"
            )

        self.assertEqual([p.name for p in matches], ["r2.running.cfg"])


class CopyGitSourceFilesIntoTests(unittest.TestCase):
    def test_uses_unique_index_prefixed_names(self) -> None:
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dest_dir:
            src = Path(src_dir)
            dest = Path(dest_dir)

            file_a = src / "a"
            file_a.mkdir()
            (file_a / "r1.cfg").write_text("hostname R1\n", encoding="utf-8")

            file_b = src / "b"
            file_b.mkdir()
            (file_b / "r1.cfg").write_text("hostname R1B\n", encoding="utf-8")

            copy_git_source_files_into(dest, [file_a / "r1.cfg", file_b / "r1.cfg"])

            copied = sorted(dest.iterdir())
            self.assertEqual(len(copied), 2)
            self.assertEqual(copied[0].read_text(encoding="utf-8"), "hostname R1\n")
            self.assertEqual(copied[1].read_text(encoding="utf-8"), "hostname R1B\n")


if __name__ == "__main__":
    unittest.main()
