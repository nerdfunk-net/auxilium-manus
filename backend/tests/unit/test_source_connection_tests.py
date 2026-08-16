"""Unit tests for Settings-based source connection tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.safe_urls import UnsafeURLError, validate_git_remote_url
from models.git_repositories import GitAuthType
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
    """git_source_service.test_connection() is a thin adapter over GitConnectionService —
    see tests/unit/test_git_connection_service.py for the real subprocess/redaction coverage."""

    def test_requires_url(self) -> None:
        result = git_source_service.test_connection(url="", token="secret")
        self.assertFalse(result["success"])
        self.assertIn("URL is required", result["message"])

    @patch("services.sources.git.git_source_service.GitConnectionService")
    def test_builds_token_auth_request_and_success_message(
        self, mock_service_cls: MagicMock
    ) -> None:
        from models.git_repositories import GitConnectionTestResponse

        mock_service_cls.return_value.test_connection.return_value = GitConnectionTestResponse(
            success=True,
            message="Git connection successful",
            details={"branch": "main"},
        )

        result = git_source_service.test_connection(
            url="https://github.com/org/repo.git",
            branch="main",
            username="git",
            token="secret-token",
            verify_ssl=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Connection successful (branch 'main')")

        request = mock_service_cls.return_value.test_connection.call_args.args[0]
        self.assertEqual(request.url, "https://github.com/org/repo.git")
        self.assertEqual(request.branch, "main")
        self.assertEqual(request.auth_type, GitAuthType.TOKEN)
        self.assertEqual(request.username, "git")
        self.assertEqual(request.token, "secret-token")
        self.assertTrue(request.verify_ssl)

    @patch("services.sources.git.git_source_service.GitConnectionService")
    def test_failure_merges_error_detail_into_message(self, mock_service_cls: MagicMock) -> None:
        from models.git_repositories import GitConnectionTestResponse

        mock_service_cls.return_value.test_connection.return_value = GitConnectionTestResponse(
            success=False,
            message="Git connection failed",
            details={"error": "repository not found", "return_code": 128},
        )

        result = git_source_service.test_connection(
            url="https://github.com/org/repo.git", token="secret-token"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Git connection failed: repository not found")

    @patch("services.sources.git.git_source_service.GitConnectionService")
    def test_failure_without_error_detail_keeps_response_message(
        self, mock_service_cls: MagicMock
    ) -> None:
        from models.git_repositories import GitConnectionTestResponse

        mock_service_cls.return_value.test_connection.return_value = GitConnectionTestResponse(
            success=False,
            message="Git remote URL must use https or ssh, got 'file'",
            details={},
        )

        result = git_source_service.test_connection(url="file:///tmp/x", token="secret-token")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Git remote URL must use https or ssh, got 'file'")


class GitSourceUnsafeUrlTests(unittest.TestCase):
    """End-to-end through the real GitConnectionService — proves unsafe URLs never
    reach a subprocess call, without mocking GitConnectionService itself."""

    @patch("services.git.connection.subprocess.run")
    def test_file_scheme_rejected_without_clone(self, mock_run: MagicMock) -> None:
        result = git_source_service.test_connection(
            url="file:///tmp/x", token="secret-token"
        )
        self.assertFalse(result["success"])
        mock_run.assert_not_called()

    @patch("services.git.connection.subprocess.run")
    def test_http_scheme_rejected_without_clone_in_production(self, mock_run: MagicMock) -> None:
        with patch("core.safe_urls.settings.environment", "production"):
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

    def test_rejects_http_scheme_in_production(self) -> None:
        with patch("core.safe_urls.settings.environment", "production"):
            with self.assertRaises(UnsafeURLError):
                validate_git_remote_url("http://git.example.com/org/repo.git")

    def test_allows_http_scheme_in_development(self) -> None:
        with patch("core.safe_urls.settings.environment", "development"):
            result = validate_git_remote_url("http://git.example.com/org/repo.git")
        self.assertEqual(result, "http://git.example.com/org/repo.git")

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
