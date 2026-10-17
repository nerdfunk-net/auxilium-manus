"""Tests for git repository path resolution (M1) and in-repo containment (S8)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import PROJECT_ROOT
from core.domain_exceptions import AccessDeniedError
from services.git.paths import repo_path, resolve_within_repo


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


class ResolveWithinRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "data" / "git" / "foo"
        (self.root / "sub").mkdir(parents=True)
        (self.root / "sub" / "c.txt").write_text("ok")
        # Sibling repo that shares a name prefix with self.root.
        self.sibling = Path(self._tmp.name) / "data" / "git" / "foo-other"
        self.sibling.mkdir(parents=True)
        (self.sibling / "secret").write_text("secret")

    def test_allows_nested_path(self) -> None:
        result = resolve_within_repo(self.root, "sub/c.txt")
        self.assertEqual(result, (self.root / "sub" / "c.txt").resolve())

    def test_allows_empty_relative(self) -> None:
        self.assertEqual(resolve_within_repo(self.root, None), self.root.resolve())
        self.assertEqual(resolve_within_repo(self.root, ""), self.root.resolve())

    def test_rejects_sibling_prefix(self) -> None:
        # The old `startswith` check treated ".../foo-other" as inside ".../foo".
        with self.assertRaises(AccessDeniedError):
            resolve_within_repo(self.root, "../foo-other/secret")

    def test_rejects_parent_escape(self) -> None:
        with self.assertRaises(AccessDeniedError):
            resolve_within_repo(self.root, "../../../etc/passwd")

    def test_rejects_absolute_relative(self) -> None:
        with self.assertRaises(AccessDeniedError):
            resolve_within_repo(self.root, "/etc/passwd")

    def test_accepts_str_or_path_root(self) -> None:
        self.assertEqual(
            resolve_within_repo(str(self.root), "sub"), (self.root / "sub").resolve()
        )


if __name__ == "__main__":
    unittest.main()


class HostileInputTests(unittest.TestCase):
    """FP-01 step 1: shared containment helpers."""

    def test_validate_relative_glob_rejects_hostile_input(self) -> None:
        from services.git.paths import validate_relative_glob

        for bad in ("/etc/passwd", "C:\\x", "../x", "a/../../b", ".git/config", "a\x00b"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_relative_glob(bad, field="f")

    def test_validate_relative_glob_accepts_normal_values(self) -> None:
        from services.git.paths import validate_relative_glob

        self.assertEqual(validate_relative_glob("*.yaml", field="f"), "*.yaml")
        self.assertEqual(validate_relative_glob("", field="f", allow_empty=True), "")

    def test_is_contained_regular_file_rejects_symlink(self) -> None:
        from services.git.paths import is_contained_regular_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "repo").mkdir()
            (base / "secret.env").write_text("SECRET_KEY=hunter2")
            (base / "repo" / "ok.txt").write_text("ok")
            (base / "repo" / "link.txt").symlink_to(base / "secret.env")
            self.assertTrue(is_contained_regular_file(base / "repo", base / "repo" / "ok.txt"))
            self.assertFalse(is_contained_regular_file(base / "repo", base / "repo" / "link.txt"))

    def test_resolve_within_repo_refuses_dot_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            (Path(tmp) / ".git" / "config").write_text("x")
            with self.assertRaises(AccessDeniedError):
                resolve_within_repo(tmp, ".git/config")

    def test_write_text_within_repo_refuses_symlink_component(self) -> None:
        from services.git.paths import write_text_within_repo

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "repo").mkdir()
            victim = base / "victim.py"
            victim.write_text("print('original')")
            (base / "repo" / "backups").symlink_to(base)
            with self.assertRaises(AccessDeniedError):
                write_text_within_repo(base / "repo", "backups/victim.py", "pwned")
            self.assertEqual(victim.read_text(), "print('original')")
            (base / "repo" / "link.cfg").symlink_to(victim)
            with self.assertRaises(AccessDeniedError):
                write_text_within_repo(base / "repo", "link.cfg", "pwned")
            self.assertEqual(victim.read_text(), "print('original')")

    def test_write_text_within_repo_writes_regular_file(self) -> None:
        from services.git.paths import write_text_within_repo

        with tempfile.TemporaryDirectory() as tmp:
            target = write_text_within_repo(tmp, "a/b.txt", "hello")
            self.assertEqual(target.read_text(), "hello")

    def test_absolute_pattern_cannot_leave_repo(self) -> None:
        from services.git.paths import list_repo_files

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "repo").mkdir()
            (base / "outside").mkdir()
            secret = base / "outside" / "secret.csv"
            secret.write_text("SECRET_KEY=hunter2-long-value")
            with self.assertRaises(ValueError):
                list_repo_files(base / "repo", "", str(secret))
            with self.assertRaises(ValueError):
                list_repo_files(base / "repo", "../outside", "*.csv")
