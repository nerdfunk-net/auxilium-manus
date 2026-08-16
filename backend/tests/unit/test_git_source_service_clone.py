"""Unit tests for git_source_service.clone_or_pull / remove_and_clone.

These delegate to the shared GitService engine (services/git/service.py) — see the
module docstring in services/sources/git/git_source_service.py. GitService itself is
exercised directly in tests/unit/test_git_service_url_validation.py.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from git import GitCommandError

from core.safe_urls import UnsafeURLError
from services.sources.git.git_source_service import (
    clone_or_pull,
    remove_and_clone,
    source_config_to_git_repository,
)


def _source_config(**overrides: object) -> dict[str, object]:
    return {
        "source_id": "gitea",
        "url": "https://example.com/admin/export.git",
        "branch": "main",
        "token": "secret",
        "username": "admin",
        **overrides,
    }


class SourceConfigToGitRepositoryTests(unittest.TestCase):
    def test_maps_fields_and_defaults_path_to_source_id(self) -> None:
        repository = source_config_to_git_repository(_source_config())
        self.assertEqual(repository["path"], "gitea")
        self.assertEqual(repository["id"], "gitea")
        self.assertEqual(repository["auth_type"], "token")
        self.assertEqual(repository["token"], "secret")

    def test_repository_path_override(self) -> None:
        repository = source_config_to_git_repository(
            _source_config(repository_path="/configs")
        )
        self.assertEqual(repository["path"], "configs")


class ClonePullDelegationTests(unittest.TestCase):
    def test_no_url_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no URL configured"):
            clone_or_pull(_source_config(url=""))

    def test_unsafe_url_from_git_service_becomes_value_error(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.get_repo_path.return_value = Path("/tmp/does-not-matter")
            git_service.open_or_clone.side_effect = UnsafeURLError("bad scheme")
            build.return_value = git_service

            with self.assertRaisesRegex(ValueError, "unsafe URL"):
                clone_or_pull(_source_config(url="http://127.0.0.1:3030/x.git"))

    def test_pull_failure_on_existing_repo_is_swallowed(self) -> None:
        import service_factory as real_service_factory

        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "gitea"
            (repo_dir / ".git").mkdir(parents=True)

            with patch.object(real_service_factory, "build_git_service") as build:
                git_service = MagicMock()
                git_service.get_repo_path.return_value = repo_dir
                git_service.open_or_clone.return_value = MagicMock()
                git_service.pull.return_value = MagicMock(success=False, message="network blip")
                build.return_value = git_service

                result = clone_or_pull(_source_config())

        self.assertEqual(result, repo_dir)
        git_service.pull.assert_called_once()

    def test_clone_command_error_becomes_runtime_error(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.get_repo_path.return_value = Path("/tmp/data/git/gitea")
            git_service.open_or_clone.side_effect = GitCommandError("clone", 128)
            build.return_value = git_service

            with self.assertRaisesRegex(RuntimeError, "Failed to clone"):
                clone_or_pull(_source_config())


class RemoveAndCloneDelegationTests(unittest.TestCase):
    def test_delegates_to_git_service_clone(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            repo_dir = Path("/tmp/data/git/gitea")
            git_service.get_repo_path.return_value = repo_dir
            build.return_value = git_service

            result = remove_and_clone(_source_config())

        git_service.clone.assert_called_once()
        self.assertEqual(result, repo_dir)

    def test_unsafe_url_becomes_value_error(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.clone.side_effect = UnsafeURLError("bad scheme")
            build.return_value = git_service

            with self.assertRaisesRegex(ValueError, "unsafe URL"):
                remove_and_clone(_source_config(url="http://127.0.0.1:3030/x.git"))


if __name__ == "__main__":
    unittest.main()
