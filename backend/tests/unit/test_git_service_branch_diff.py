"""GitService.checkout_new_branch + diff_refs — used by open-change-request.

Runs against real file:// repos in a TemporaryDirectory (no network).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _git_repo_builder import make_repo_with_remote
from git import Repo

from services.git.service import GitService


class GitServiceBranchDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _work, self.bare = make_repo_with_remote(self.root)
        self.clone_target = self.root / "managed"

        self.repo_cfg = {
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
        self.repo: Repo = self.service.open_or_clone(self.repo_cfg)

    def test_checkout_new_branch_creates_ref_from_base(self) -> None:
        self.service.checkout_new_branch(self.repo, "manus/cr-1", "main")
        self.assertEqual(self.repo.active_branch.name, "manus/cr-1")
        # Idempotent: -B resets the branch instead of failing.
        self.service.checkout_new_branch(self.repo, "manus/cr-1", "main")
        self.assertEqual(self.repo.active_branch.name, "manus/cr-1")

    def test_diff_refs_reports_what_branch_adds(self) -> None:
        self.service.checkout_new_branch(self.repo, "manus/cr-1", "main")
        target = Path(self.repo.working_tree_dir) / "router1.cfg"
        target.write_text("hostname router1\n", encoding="utf-8")
        self.service.commit(
            self.repo_cfg, message="add router1", files=["router1.cfg"], repo=self.repo
        )

        diff = self.service.diff_refs(self.repo, "main", "manus/cr-1")
        self.assertIn("router1.cfg", diff)
        self.assertIn("+hostname router1", diff)

    def test_push_force_creates_remote_branch(self) -> None:
        self.service.checkout_new_branch(self.repo, "manus/cr-1", "main")
        target = Path(self.repo.working_tree_dir) / "router1.cfg"
        target.write_text("hostname router1\n", encoding="utf-8")
        self.service.commit(
            self.repo_cfg, message="add router1", files=["router1.cfg"], repo=self.repo
        )

        result = self.service.push(
            self.repo_cfg, repo=self.repo, branch="manus/cr-1", force=True
        )
        self.assertTrue(result.success)
        self.assertEqual(result.branch, "manus/cr-1")
        self.assertIn("manus/cr-1", Repo(self.bare).heads)


if __name__ == "__main__":
    unittest.main()
