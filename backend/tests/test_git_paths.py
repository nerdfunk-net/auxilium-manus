"""Tests for git repository path resolution (M1)."""

from __future__ import annotations

import unittest

from core.config import PROJECT_ROOT
from services.git.paths import repo_path


class GitPathsTests(unittest.TestCase):
    def test_happy_path_uses_path(self) -> None:
        result = repo_path({"name": "my-configs", "path": "configs"})
        self.assertEqual(result, (PROJECT_ROOT / "data" / "git" / "configs").resolve())

    def test_nested_subdirectory(self) -> None:
        result = repo_path({"name": "x", "path": "team/a"})
        self.assertEqual(result, (PROJECT_ROOT / "data" / "git" / "team" / "a").resolve())

    def test_falls_back_to_name(self) -> None:
        result = repo_path({"name": "my-repo"})
        self.assertEqual(result, (PROJECT_ROOT / "data" / "git" / "my-repo").resolve())

    def test_rejects_parent_segments(self) -> None:
        for bad in ("../../etc", "../x", ".."):
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    repo_path({"name": "safe", "path": bad})

    def test_rejects_name_parent(self) -> None:
        with self.assertRaises(ValueError):
            repo_path({"name": ".."})

    def test_rejects_absolute_path(self) -> None:
        with self.assertRaises(ValueError):
            repo_path({"name": "safe", "path": "/etc/passwd"})

    def test_rejects_empty_or_whitespace(self) -> None:
        with self.assertRaises(ValueError):
            repo_path({"name": "safe", "path": "   "})
        with self.assertRaises(ValueError):
            repo_path({"name": "", "path": None})
        with self.assertRaises(ValueError):
            repo_path({})


if __name__ == "__main__":
    unittest.main()
