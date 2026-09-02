"""Unit tests for GitConnectionService — the shared "test connection" implementation
used by the Git Repositories feature.
"""

from __future__ import annotations

import os
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
    def setUp(self) -> None:
        # S7: the service must never leave GIT_* vars in the process environment.
        for key in ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT", "GIT_SSH_COMMAND"):
            os.environ.pop(key, None)
            self.addCleanup(os.environ.pop, key, None)

    @patch("services.git.connection.subprocess.run")
    def test_success_on_zero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = GitConnectionService().test_connection(_request())

        self.assertTrue(result.success)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "git")
        self.assertIn("--depth", cmd)
        self.assertIn("main", cmd)

    @patch("services.git.connection.subprocess.run")
    def test_clone_runs_with_explicit_env_and_no_environ_mutation(
        self, mock_run: MagicMock
    ) -> None:
        """S7: the subprocess gets an explicit env mapping and os.environ is untouched,
        even for a verify_ssl=False repository."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = GitConnectionService().test_connection(_request(verify_ssl=False))

        self.assertTrue(result.success)
        passed_env = mock_run.call_args.kwargs["env"]
        self.assertIsInstance(passed_env, dict)
        self.assertEqual(passed_env.get("GIT_SSL_NO_VERIFY"), "1")
        self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)

    @patch("services.git.connection.subprocess.run")
    def test_inline_token_without_credential_name_is_used(self, mock_run: MagicMock) -> None:
        """Regression test: an inline token with no credential_name must still be
        embedded in the clone URL, not silently dropped."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = GitConnectionService().test_connection(
            _request(credential_name=None, username="git", token="secret-token")
        )

        self.assertTrue(result.success)
        cmd = mock_run.call_args.args[0]
        clone_url = cmd[-2]
        self.assertIn("secret-token", clone_url)

    @patch("services.git.connection.subprocess.run")
    def test_failure_details_never_include_stderr(self, mock_run: MagicMock) -> None:
        """M6: client-facing details must never carry raw clone stderr (which may
        contain the auth URL/token) — only a sanitized message and return_code."""
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
    def test_logs_redact_token_from_failure_stderr(self, mock_run: MagicMock) -> None:
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
