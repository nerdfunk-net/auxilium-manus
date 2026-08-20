"""Unit tests for GitConnectionService — the shared "test connection" implementation
used by both the Git Repositories feature and (via services.sources.git.git_source_service)
Settings-based git sources.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.git_repositories import GitAuthType, GitConnectionTestRequest
from services.git.connection import GitConnectionService


def _request(**overrides: object) -> GitConnectionTestRequest:
    defaults: dict[str, object] = {
        "url": "https://github.com/org/repo.git",
        "branch": "main",
        "auth_type": GitAuthType.TOKEN,
        "username": "git",
        "token": "secret-token",
        "verify_ssl": True,
    }
    defaults.update(overrides)
    return GitConnectionTestRequest(**defaults)


class GitConnectionServiceTests(unittest.TestCase):
    @patch("services.git.connection.subprocess.run")
    @patch("services.git.connection.set_ssl_env")
    def test_success_on_zero_exit(self, mock_ssl_env: MagicMock, mock_run: MagicMock) -> None:
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = GitConnectionService().test_connection(_request())

        self.assertTrue(result.success)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "git")
        self.assertIn("--depth", cmd)
        self.assertIn("main", cmd)

    @patch("services.git.connection.subprocess.run")
    @patch("services.git.connection.set_ssl_env")
    def test_inline_token_without_credential_name_is_used(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock
    ) -> None:
        """Regression test: an inline token with no credential_name must still be
        embedded in the clone URL, not silently dropped."""
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = GitConnectionService().test_connection(
            _request(credential_name=None, username="git", token="secret-token")
        )

        self.assertTrue(result.success)
        cmd = mock_run.call_args.args[0]
        clone_url = cmd[-2]
        self.assertIn("secret-token", clone_url)

    @patch("services.git.connection.subprocess.run")
    @patch("services.git.connection.set_ssl_env")
    def test_failure_details_never_include_stderr(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock
    ) -> None:
        """M6: client-facing details must never carry raw clone stderr (which may
        contain the auth URL/token) — only a sanitized message and return_code."""
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: could not read from 'https://git:secret-token@github.com/org/repo.git'",
        )

        result = GitConnectionService().test_connection(_request())

        self.assertFalse(result.success)
        self.assertNotIn("error", result.details or {})
        self.assertEqual((result.details or {}).get("return_code"), 128)

    @patch("services.git.connection.subprocess.run")
    @patch("services.git.connection.set_ssl_env")
    def test_logs_redact_token_from_failure_stderr(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: could not read from 'https://git:secret-token@github.com/org/repo.git'",
        )

        with self.assertLogs("services.git.connection", level="WARNING") as logs:
            GitConnectionService().test_connection(_request())

        log_output = "\n".join(logs.output)
        self.assertNotIn("secret-token", log_output)
        self.assertIn("github.com/org/repo.git", log_output)

    @patch("services.git.connection.subprocess.run")
    def test_unsafe_url_rejected_without_clone(self, mock_run: MagicMock) -> None:
        result = GitConnectionService().test_connection(_request(url="file:///tmp/x"))

        self.assertFalse(result.success)
        mock_run.assert_not_called()

    @patch("services.git.connection.subprocess.run")
    def test_empty_url_rejected(self, mock_run: MagicMock) -> None:
        result = GitConnectionService().test_connection(_request(url=""))

        self.assertFalse(result.success)
        self.assertIn("URL is required", result.message)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
