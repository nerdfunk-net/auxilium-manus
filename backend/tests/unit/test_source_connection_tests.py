"""Unit tests for Settings-based source connection tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.safe_urls import UnsafeURLError, validate_git_remote_url
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.credentials import NautobotCredentials
from services.sources.git import git_source_service


class NautobotTestConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_when_status_returns_data(self) -> None:
        from services.nautobot.client import NautobotService

        service = NautobotService()
        service.rest_request = AsyncMock(
            return_value={"nautobot-version": "2.3.0"}
        )
        credentials = NautobotCredentials(url="https://nb.example", token="tok")

        result = await service.test_connection(credentials)

        self.assertEqual(result["nautobot-version"], "2.3.0")
        service.rest_request.assert_awaited_once_with("status/", credentials)

    async def test_raises_when_rest_request_fails(self) -> None:
        from services.nautobot.client import NautobotService

        service = NautobotService()
        service.rest_request = AsyncMock(
            side_effect=NautobotAPIError("REST request failed with status 403")
        )
        credentials = NautobotCredentials(url="https://nb.example", token="bad")

        with self.assertRaises(NautobotAPIError) as ctx:
            await service.test_connection(credentials)

        self.assertIn("403", str(ctx.exception))


class GitSourceTestConnectionTests(unittest.TestCase):
    def test_requires_url(self) -> None:
        result = git_source_service.test_connection(url="", token="secret")
        self.assertFalse(result["success"])
        self.assertIn("URL is required", result["message"])

    @patch("services.sources.git.git_source_service.validate_git_remote_url")
    @patch("services.sources.git.git_source_service.subprocess.run")
    @patch("services.sources.git.git_source_service.set_ssl_env")
    def test_success_on_zero_exit(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock, mock_validate: MagicMock
    ) -> None:
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = git_source_service.test_connection(
            url="https://github.com/org/repo.git",
            branch="main",
            username="git",
            token="secret-token",
            verify_ssl=True,
        )

        self.assertTrue(result["success"])
        self.assertIn("Connection successful", result["message"])
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "git")
        self.assertIn("--depth", cmd)
        self.assertIn("main", cmd)
        # Auth URL embeds credentials; public URL must not appear alone as the clone target
        self.assertTrue(any("secret-token" in part for part in cmd))

    @patch("services.sources.git.git_source_service.validate_git_remote_url")
    @patch("services.sources.git.git_source_service.subprocess.run")
    @patch("services.sources.git.git_source_service.set_ssl_env")
    def test_redacts_token_from_failure_message(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock, mock_validate: MagicMock
    ) -> None:
        mock_ssl_env.return_value.__enter__ = MagicMock(return_value=None)
        mock_ssl_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: could not read from 'https://git:secret-token@github.com/org/repo.git'",
        )

        result = git_source_service.test_connection(
            url="https://github.com/org/repo.git",
            branch="main",
            username="git",
            token="secret-token",
        )

        self.assertFalse(result["success"])
        self.assertNotIn("secret-token", result["message"])
        self.assertIn("github.com/org/repo.git", result["message"])


class GitSourceUnsafeUrlTests(unittest.TestCase):
    @patch("services.sources.git.git_source_service.subprocess.run")
    def test_file_scheme_rejected_without_clone(self, mock_run: MagicMock) -> None:
        result = git_source_service.test_connection(
            url="file:///tmp/x", token="secret-token"
        )
        self.assertFalse(result["success"])
        mock_run.assert_not_called()

    @patch("services.sources.git.git_source_service.subprocess.run")
    def test_http_scheme_rejected_without_clone(self, mock_run: MagicMock) -> None:
        result = git_source_service.test_connection(
            url="http://git.example.com/org/repo.git", token="secret-token"
        )
        self.assertFalse(result["success"])
        mock_run.assert_not_called()


class ValidateGitRemoteUrlTests(unittest.TestCase):
    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_https(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        result = validate_git_remote_url("https://git.example.com/org/repo.git")
        self.assertEqual(result, "https://git.example.com/org/repo.git")

    def test_accepts_scp_like_syntax(self) -> None:
        result = validate_git_remote_url("git@git.example.com:org/repo.git")
        self.assertEqual(result, "git@git.example.com:org/repo.git")

    def test_accepts_ssh_scheme(self) -> None:
        result = validate_git_remote_url("ssh://git@git.example.com/org/repo.git")
        self.assertEqual(result, "ssh://git@git.example.com/org/repo.git")

    def test_rejects_file_scheme(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("file:///tmp/repo.git")

    def test_rejects_http_scheme(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("http://git.example.com/org/repo.git")

    def test_rejects_bare_filesystem_path(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("/var/git/repo.git")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("")

    def test_rejects_embedded_credentials_on_https(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("https://user:pass@git.example.com/org/repo.git")


if __name__ == "__main__":
    unittest.main()
