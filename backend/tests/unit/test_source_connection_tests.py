"""Unit tests for Settings-based source connection tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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

    @patch("services.sources.git.git_source_service.subprocess.run")
    @patch("services.sources.git.git_source_service.set_ssl_env")
    def test_success_on_zero_exit(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock
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

    @patch("services.sources.git.git_source_service.subprocess.run")
    @patch("services.sources.git.git_source_service.set_ssl_env")
    def test_redacts_token_from_failure_message(
        self, mock_ssl_env: MagicMock, mock_run: MagicMock
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


if __name__ == "__main__":
    unittest.main()
