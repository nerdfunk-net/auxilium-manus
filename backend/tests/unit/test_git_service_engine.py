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

        path_patch = patch.object(GitService, "get_repo_path", return_value=self.clone_target)
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
        self.assertEqual(Repo(repo.working_dir).remotes.origin.url, f"file://{other_bare}")

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

    def test_commit_and_push_refuse_when_the_lease_was_lost(self) -> None:
        from unittest.mock import MagicMock

        from services.git import repo_lock
        from services.git.failure import GitOperationError

        repo = self.service.open_or_clone(self.repo)
        (Path(repo.working_dir) / "late.txt").write_text("x\n")
        lease = MagicMock()
        lease.ensure_held.side_effect = GitOperationError("lease expired")
        token = repo_lock._current_lease.set(lease)
        try:
            with self.assertRaises(GitOperationError):
                self.service.commit(self.repo, "late", add_all=True)
            with self.assertRaises(GitOperationError):
                self.service.push(self.repo, repo=repo)
        finally:
            repo_lock._current_lease.reset(token)
        # nothing was staged by the refused commit
        self.assertEqual(repo.git.diff("--cached", "--name-only"), "")

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
        # push two new commits through the seed working copy
        for i in range(2):
            (self.work / f"upstream{i}.txt").write_text("up\n")
            git("add", "-A", cwd=self.work)
            git("commit", "-m", f"upstream change {i}", cwd=self.work)
        git("push", "origin", "main", cwd=self.work)

        result = self.service.pull(self.repo)
        self.assertIsInstance(result, PullResult)
        self.assertTrue(result.success)
        self.assertTrue((self.clone_target / "upstream1.txt").exists())
        # commits_pulled counts real commits, not FetchInfo entries
        self.assertEqual(result.commits_pulled, 2)

    def test_pull_up_to_date_reports_zero_commits(self) -> None:
        self.service.open_or_clone(self.repo)
        result = self.service.pull(self.repo)
        self.assertTrue(result.success)
        self.assertEqual(result.commits_pulled, 0)

    def test_pull_failure_returns_unsuccessful_result(self) -> None:
        bad = {**self.repo, "url": f"file://{self.root / 'missing.git'}"}
        with patch.object(GitService, "get_repo_path", return_value=self.root / "bad"):
            result = GitService().pull(bad)
        self.assertFalse(result.success)

    # --- C5-01 / C5-03: branch discipline of the shared working tree ----------------------

    def _checkout_cr_branch(self, repo: Repo, name: str = "manus/cr-1") -> None:
        self.service.checkout_new_branch(repo, name, "main")

    def test_open_or_clone_returns_to_configured_branch(self) -> None:
        repo = self.service.open_or_clone(self.repo)
        self._checkout_cr_branch(repo)
        self.assertEqual(repo.active_branch.name, "manus/cr-1")
        again = self.service.open_or_clone(self.repo)
        self.assertEqual(again.active_branch.name, "main")

    def test_open_or_clone_refuses_dirty_tree_on_wrong_branch(self) -> None:
        from services.git.failure import GitOperationError

        repo = self.service.open_or_clone(self.repo)
        self._checkout_cr_branch(repo)
        scratch = self.clone_target / "unsaved.txt"
        scratch.write_text("work in progress\n")
        with self.assertRaises(GitOperationError) as ctx:
            self.service.open_or_clone(self.repo)
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")
        self.assertIn("Git Clone", str(ctx.exception))
        self.assertTrue(scratch.exists())  # working file untouched

    def test_pull_never_merges_into_the_wrong_branch(self) -> None:
        # The newly noticed variant: HEAD on main, pulling the CR branch must not merge it.
        repo = self.service.open_or_clone(self.repo)
        self._checkout_cr_branch(repo)
        (self.clone_target / "cr.txt").write_text("reviewed change\n")
        self.service.commit(self.repo, "cr", add_all=True, repo=repo)
        git("push", "-u", "origin", "manus/cr-1", cwd=self.clone_target)
        repo.git.checkout("main")

        result = self.service.pull({**self.repo, "branch": "manus/cr-1"}, repo=repo)

        self.assertTrue(result.success)
        self.assertEqual(repo.active_branch.name, "manus/cr-1")
        repo.git.checkout("main")
        self.assertFalse((self.clone_target / "cr.txt").exists())  # main never got the CR change

    def test_unexpected_error_does_not_delete_the_tree(self) -> None:
        self.service.open_or_clone(self.repo)
        (self.clone_target / "precious.txt").write_text("keep me\n")
        with patch("services.git.service.Repo", side_effect=OSError("transient")):
            with self.assertRaises(OSError):
                self.service.open_or_clone(self.repo)
        self.assertTrue((self.clone_target / "precious.txt").exists())

    def test_corrupt_tree_is_moved_aside_not_deleted(self) -> None:
        self.clone_target.mkdir(parents=True)
        (self.clone_target / "stray.txt").write_text("not a repository\n")
        repo = self.service.open_or_clone(self.repo)
        self.assertTrue((self.clone_target / "README.md").exists())
        aside = list(self.root.glob("managed.corrupt-*"))
        self.assertEqual(len(aside), 1)
        self.assertTrue((aside[0] / "stray.txt").exists())
        self.assertIsInstance(repo, Repo)

    def test_clone_keeps_old_tree_when_clone_fails(self) -> None:
        self.service.open_or_clone(self.repo)
        (self.clone_target / "keep.txt").write_text("unpushed\n")
        bad = {**self.repo, "url": f"file://{self.root / 'missing.git'}"}
        with self.assertRaises(Exception):  # noqa: B017 - any clone error
            self.service.clone(bad)
        self.assertTrue((self.clone_target / "keep.txt").exists())

    def test_stage_cr_then_backup_reaches_main(self) -> None:
        """Section 9 reproduction as a test: after staging a CR on the shared tree, a later
        backup commit lands on main and is pushed to the remote main."""
        from services.git.tree_scope import git_branch_scope

        repo = self.service.open_or_clone(self.repo)
        with git_branch_scope(self.service, repo, self.repo, "manus/cr-1", "origin/main"):
            (self.clone_target / "cr.txt").write_text("staged\n")
            self.service.commit(self.repo, "stage", add_all=True, repo=repo)
            self.service.push(self.repo, repo=repo, branch="manus/cr-1", force=True)
        self.assertEqual(repo.active_branch.name, "main")

        repo = self.service.open_or_clone(self.repo)
        (self.clone_target / "backup.cfg").write_text("hostname r1\n")
        self.service.commit(self.repo, "nightly backup", add_all=True, repo=repo)
        result = self.service.push(self.repo, repo=repo)
        self.assertTrue(result.success)
        bare = Repo(self.bare)
        self.assertIn("backup.cfg", bare.git.show("--stat", "main"))
        self.assertNotIn("cr.txt", bare.git.show("--stat", "main"))

    def test_failed_branch_restore_fails_a_clean_block(self) -> None:
        from git.exc import GitCommandError

        from services.git.failure import GitOperationError
        from services.git.tree_scope import git_branch_scope

        repo = self.service.open_or_clone(self.repo)
        with patch.object(GitService, "ensure_branch", side_effect=GitCommandError("checkout", 1)):
            with self.assertRaises(GitOperationError) as ctx:
                with git_branch_scope(self.service, repo, self.repo, "manus/cr-2", "origin/main"):
                    pass
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")

    def test_failed_branch_restore_does_not_mask_the_blocks_error(self) -> None:
        from git.exc import GitCommandError

        from services.git.tree_scope import git_branch_scope

        repo = self.service.open_or_clone(self.repo)
        with patch.object(GitService, "ensure_branch", side_effect=GitCommandError("checkout", 1)):
            with self.assertRaisesRegex(ValueError, "deploy failed"):
                with git_branch_scope(self.service, repo, self.repo, "manus/cr-3", "origin/main"):
                    raise ValueError("deploy failed")

    def test_fetch_success_and_failure(self) -> None:
        self.service.open_or_clone(self.repo)
        ok = self.service.fetch(self.repo)
        self.assertTrue(ok.success)

        with patch.object(GitService, "get_repo_path", return_value=self.root / "nope"):
            bad = GitService().fetch({**self.repo, "url": f"file://{self.root / 'x.git'}"})
        self.assertFalse(bad.success)


if __name__ == "__main__":
    unittest.main()
