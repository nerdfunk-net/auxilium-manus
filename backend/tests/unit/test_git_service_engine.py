"""Tests for services/git/service.py (GitService) against real file:// repos.

The outbound-URL guard is patched to a no-op so ``file://`` remotes are usable;
repo paths are redirected into a TemporaryDirectory.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _git_repo_builder import git, make_repo_with_remote
from git import Repo

from services.git.service import CommitResult, GitService, PullResult


class GitServiceEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.work, self.bare = make_repo_with_remote(self.root)
        self.clone_target = self.root / "managed"

        self.repo = {
            "name": "managed",
            "url": f"file://{self.bare}",
            "branch": "main",
            "auth_type": "none",
            "git_author_name": "Bot",
            "git_author_email": "bot@test.local",
        }

        url_patch = patch("services.git.service.validate_git_remote_url", return_value="ok")
        self.addCleanup(url_patch.stop)
        url_patch.start()

        path_patch = patch.object(
            GitService, "get_repo_path", return_value=self.clone_target
        )
        self.addCleanup(path_patch.stop)
        path_patch.start()

        self.service = GitService()

    def test_open_or_clone_clones_when_missing(self) -> None:
        repo = self.service.open_or_clone(self.repo)
        self.assertIsInstance(repo, Repo)
        self.assertTrue((self.clone_target / "README.md").exists())

    def test_open_or_clone_reuses_existing_checkout(self) -> None:
        first = self.service.open_or_clone(self.repo)
        second = self.service.open_or_clone(self.repo)
        self.assertEqual(first.working_dir, second.working_dir)

    def test_open_or_clone_reclones_on_url_mismatch(self) -> None:
        self.service.open_or_clone(self.repo)
        other_bare = self.root / "other.git"
        git("clone", "--bare", str(self.bare), str(other_bare), cwd=self.root)
        repo = self.service.open_or_clone({**self.repo, "url": f"file://{other_bare}"})
        self.assertEqual(
            Repo(repo.working_dir).remotes.origin.url, f"file://{other_bare}"
        )

    def test_clone_to_explicit_path(self) -> None:
        target = self.root / "explicit"
        repo = self.service.clone(self.repo, target_path=target)
        self.assertTrue((target / "README.md").exists())
        self.assertEqual(Path(repo.working_dir), target)

    def test_commit_reports_no_changes(self) -> None:
        self.service.open_or_clone(self.repo)
        result = self.service.commit(self.repo, "noop")
        self.assertIsInstance(result, CommitResult)
        self.assertTrue(result.success)
        self.assertEqual(result.files_changed, 0)

    def test_commit_stages_and_commits_new_file(self) -> None:
        repo = self.service.open_or_clone(self.repo)
        (Path(repo.working_dir) / "new.txt").write_text("data\n")
        result = self.service.commit(self.repo, "add new", files=["new.txt"])
        self.assertTrue(result.success)
        self.assertEqual(result.files_changed, 1)
        self.assertIsNotNone(result.commit_sha)

    def test_commit_add_all(self) -> None:
        repo = self.service.open_or_clone(self.repo)
        (Path(repo.working_dir) / "a.txt").write_text("a\n")
        (Path(repo.working_dir) / "b.txt").write_text("b\n")
        result = self.service.commit(self.repo, "add all", add_all=True)
        self.assertEqual(result.files_changed, 2)

    def test_push_sends_local_commit_to_remote(self) -> None:
        repo = self.service.open_or_clone(self.repo)
        (Path(repo.working_dir) / "pushed.txt").write_text("x\n")
        self.service.commit(self.repo, "local", add_all=True)
        result = self.service.push(self.repo)
        self.assertTrue(result.success)
        self.assertTrue(result.pushed)
        # verify the remote actually received it
        bare = Repo(self.bare)
        self.assertIn("pushed.txt", bare.git.show("--stat", "HEAD"))

    def test_pull_brings_in_remote_commits(self) -> None:
        self.service.open_or_clone(self.repo)
        # push a new commit through the seed working copy
        (self.work / "upstream.txt").write_text("up\n")
        git("add", "-A", cwd=self.work)
        git("commit", "-m", "upstream change", cwd=self.work)
        git("push", "origin", "main", cwd=self.work)

        result = self.service.pull(self.repo)
        self.assertIsInstance(result, PullResult)
        self.assertTrue(result.success)
        self.assertTrue((self.clone_target / "upstream.txt").exists())

    def test_pull_failure_returns_unsuccessful_result(self) -> None:
        bad = {**self.repo, "url": f"file://{self.root / 'missing.git'}"}
        with patch.object(GitService, "get_repo_path", return_value=self.root / "bad"):
            result = GitService().pull(bad)
        self.assertFalse(result.success)

    def test_fetch_success_and_failure(self) -> None:
        self.service.open_or_clone(self.repo)
        ok = self.service.fetch(self.repo)
        self.assertTrue(ok.success)

        with patch.object(GitService, "get_repo_path", return_value=self.root / "nope"):
            bad = GitService().fetch({**self.repo, "url": f"file://{self.root / 'x.git'}"})
        self.assertFalse(bad.success)


if __name__ == "__main__":
    unittest.main()
