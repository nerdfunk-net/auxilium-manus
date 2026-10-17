"""Unit tests for services.git.sync.git_checkout / remove_and_clone.

These delegate to the shared GitService engine (services/git/service.py). GitService
itself is exercised directly in tests/unit/test_git_service_url_validation.py.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from git import GitCommandError

from core.safe_urls import UnsafeURLError
from services.git.sync import git_checkout, remove_and_clone


def _repository(**overrides: object) -> dict[str, object]:
    return {
        "id": 1,
        "name": "gitea",
        "url": "https://example.com/admin/export.git",
        "branch": "main",
        "auth_type": "token",
        "credential_name": "gitea-token",
        **overrides,
    }


def clone_or_pull(repository: dict, *, allow_stale: bool = False) -> Path:
    """Enter and leave the checkout, returning the root it yielded."""
    with git_checkout(repository, allow_stale=allow_stale) as root:
        return root


class ClonePullDelegationTests(unittest.TestCase):
    def test_no_url_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no URL configured"):
            clone_or_pull(_repository(url=""))

    def test_unsafe_url_from_git_service_becomes_value_error(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.get_repo_path.return_value = Path("/tmp/does-not-matter")
            git_service.open_or_clone.side_effect = UnsafeURLError("bad scheme")
            build.return_value = git_service

            with self.assertRaisesRegex(ValueError, "unsafe URL"):
                clone_or_pull(_repository(url="http://127.0.0.1:3030/x.git"))

    def test_pull_failure_on_existing_repo_raises_by_default(self) -> None:
        # C5-04: a failed pull must not silently serve a stale tree.
        import service_factory as real_service_factory
        from services.git.failure import GitOperationError

        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "gitea"
            (repo_dir / ".git").mkdir(parents=True)

            with patch.object(real_service_factory, "build_git_service") as build:
                git_service = MagicMock()
                git_service.get_repo_path.return_value = repo_dir
                git_service.open_or_clone.return_value = MagicMock()
                git_service.pull.return_value = MagicMock(
                    success=False,
                    message="network blip",
                    error=lambda: GitOperationError("network blip"),
                )
                build.return_value = git_service

                with self.assertRaises(GitOperationError):
                    clone_or_pull(_repository())

    def test_pull_failure_is_tolerated_with_allow_stale(self) -> None:
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

                result = clone_or_pull(_repository(), allow_stale=True)

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
                clone_or_pull(_repository())

    def test_lease_is_held_for_the_whole_block(self) -> None:
        import service_factory as real_service_factory

        events: list[str] = []

        @contextmanager
        def fake_lock(_repo_id: int):
            events.append("acquire")
            try:
                yield MagicMock()
            finally:
                events.append("release")

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(real_service_factory, "build_git_service") as build,
                patch("services.git.tree_scope.git_repo_lock", fake_lock),
            ):
                git_service = MagicMock()
                git_service.get_repo_path.return_value = Path(tmp)
                git_service.pull.return_value = MagicMock(success=True)
                build.return_value = git_service
                with git_checkout(_repository()):
                    events.append("read")

        self.assertEqual(events, ["acquire", "read", "release"])

    def test_stale_read_is_recorded_as_a_run_event(self) -> None:
        import service_factory as real_service_factory
        from services.execution.run_events_reporter import RunEventContext, bound_run_event_context

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(real_service_factory, "build_git_service") as build,
                patch("services.execution.run_events_reporter.emit_run_event") as emit,
            ):
                git_service = MagicMock()
                git_service.get_repo_path.return_value = Path(tmp)
                git_service.pull.return_value = MagicMock(success=False, message="offline")
                build.return_value = git_service
                with bound_run_event_context(RunEventContext(run_id=5, node_id="n1")):
                    with git_checkout(_repository(), allow_stale=True):
                        pass
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs["kind"], "git_stale")
        self.assertEqual(emit.call_args.kwargs["level"], "warning")

    def test_fresh_read_records_nothing(self) -> None:
        import service_factory as real_service_factory

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(real_service_factory, "build_git_service") as build,
                patch("services.execution.run_events_reporter.emit_run_event") as emit,
            ):
                git_service = MagicMock()
                git_service.get_repo_path.return_value = Path(tmp)
                git_service.pull.return_value = MagicMock(success=True)
                build.return_value = git_service
                with git_checkout(_repository()):
                    pass
        emit.assert_not_called()

    def test_error_in_the_callers_block_is_not_relabelled(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.get_repo_path.return_value = Path("/tmp/data/git/gitea")
            git_service.pull.return_value = MagicMock(success=True)
            build.return_value = git_service
            with self.assertRaises(GitCommandError):
                with git_checkout(_repository()):
                    raise GitCommandError("log", 1)


class RemoveAndCloneDelegationTests(unittest.TestCase):
    def test_delegates_to_git_service_clone(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            repo_dir = Path("/tmp/data/git/gitea")
            git_service.get_repo_path.return_value = repo_dir
            build.return_value = git_service

            result = remove_and_clone(_repository())

        git_service.clone.assert_called_once()
        self.assertEqual(result, repo_dir)

    def test_unsafe_url_becomes_value_error(self) -> None:
        import service_factory as real_service_factory

        with patch.object(real_service_factory, "build_git_service") as build:
            git_service = MagicMock()
            git_service.clone.side_effect = UnsafeURLError("bad scheme")
            build.return_value = git_service

            with self.assertRaisesRegex(ValueError, "unsafe URL"):
                remove_and_clone(_repository(url="http://127.0.0.1:3030/x.git"))


if __name__ == "__main__":
    unittest.main()
