"""GitService must reject unsafe git remote URLs on every real operation.

Regression coverage for the gap where store-artifact/git-push (which go through
GitService) never validated the remote URL scheme, while read-config/get-from-config
(which resolve a GitRepository and then also call GitService) did — see
doc/WORKFLOW-STEPS.md.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.safe_urls import UnsafeURLError
from services.git.service import GitService


class GitServiceUrlValidationTests(unittest.TestCase):
    """http is only rejected outside development — see core/safe_urls.py."""

    def setUp(self) -> None:
        self.git_service = GitService()
        self.enterContext(patch("core.safe_urls.settings.environment", "production"))

    def test_open_or_clone_rejects_http_url(self) -> None:
        with self.assertRaises(UnsafeURLError):
            self.git_service.open_or_clone(
                {"url": "http://127.0.0.1:3030/admin/export.git", "name": "gitea"}
            )

    def test_open_or_clone_without_dns_still_applies_the_url_policy(self) -> None:
        with self.assertRaises(UnsafeURLError):
            self.git_service.open_or_clone(
                {"url": "http://127.0.0.1:3030/admin/export.git", "name": "gitea"},
                resolve_dns=False,
            )

    def test_open_or_clone_without_dns_skips_the_lookup_for_an_existing_clone(self) -> None:
        repository = {"url": "https://example.com/a/b.git", "name": "gitea", "branch": "main"}
        with (
            patch("services.git.service.validate_git_remote_url") as validate,
            patch.object(self.git_service, "get_repo_path", return_value=Path("/tmp/x-nope")),
            patch("services.git.service.Path.mkdir"),
            patch("services.git.service.Repo") as repo_cls,
            patch.object(self.git_service, "ensure_branch"),
        ):
            repo_cls.return_value.remotes = []
            self.git_service.open_or_clone(repository, resolve_dns=False)
        self.assertFalse(validate.call_args.kwargs["resolve_dns"])

    def test_a_fresh_clone_always_resolves_dns(self) -> None:
        repository = {"url": "https://example.com/a/b.git", "name": "gitea", "branch": "main"}
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("services.git.service.validate_git_remote_url") as validate,
                patch.object(self.git_service, "get_repo_path", return_value=Path(tmp) / "r"),
                patch.object(self.git_service, "_clone_fresh") as clone_fresh,
            ):
                self.git_service.open_or_clone(repository, resolve_dns=False)
        clone_fresh.assert_called_once()  # _clone_fresh validates with DNS itself
        self.assertFalse(validate.call_args.kwargs["resolve_dns"])

    def test_clone_rejects_http_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsafeURLError):
                self.git_service.clone(
                    {"url": "http://127.0.0.1:3030/admin/export.git", "name": "gitea"},
                    target_path=Path(tmp) / "repo",
                )

    def test_pull_rejects_http_url(self) -> None:
        result = self.git_service.pull(
            {"url": "http://127.0.0.1:3030/admin/export.git", "name": "gitea"},
            repo=MagicMock(),
        )
        self.assertFalse(result.success)
        self.assertIn("https or ssh", result.message)

    def test_push_rejects_http_url(self) -> None:
        result = self.git_service.push(
            {"url": "http://127.0.0.1:3030/admin/export.git", "name": "gitea"},
            repo=MagicMock(),
        )
        self.assertFalse(result.success)
        self.assertIn("https or ssh", result.message)

    def test_clone_with_ssh_url_is_not_blocked(self) -> None:
        """ssh:// is allowed, but is now subject to the same IP allow-list as https
        (H2), so DNS resolution must be mocked to a public/RFC1918 address."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "repo"
            with patch(
                "core.safe_urls.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ):
                with patch("services.git.service.Repo.clone_from") as clone_from:
                    clone_from.return_value = MagicMock()
                    repo = self.git_service.clone(
                        {
                            "url": "ssh://git@example.com/org/repo.git",
                            "name": "x",
                            "branch": "main",
                        },
                        target_path=target,
                    )
            clone_from.assert_called_once()
            self.assertIs(repo, clone_from.return_value)


class GitServiceDevelopmentHttpTests(unittest.TestCase):
    """ENV=development (the default) allows http:// git remotes for local tooling."""

    def setUp(self) -> None:
        self.git_service = GitService()
        self.enterContext(patch("core.safe_urls.settings.environment", "development"))

    def test_clone_with_http_url_is_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "repo"
            with patch("services.git.service.Repo.clone_from") as clone_from:
                clone_from.return_value = MagicMock()
                repo = self.git_service.clone(
                    {
                        "url": "http://127.0.0.1:3030/admin/export.git",
                        "name": "gitea",
                        "branch": "main",
                    },
                    target_path=target,
                )
            clone_from.assert_called_once()
            self.assertIs(repo, clone_from.return_value)


if __name__ == "__main__":
    unittest.main()
