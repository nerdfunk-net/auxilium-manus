"""Unit tests for Settings-based source connection tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from core.safe_urls import UnsafeURLError, validate_git_remote_url
from models.ise import ISETestConnectionRequest
from models.mattermost import MattermostTestConnectionRequest
from models.pyats import PyATSTestConnectionRequest
from models.sources_nautobot import NautobotTestConnectionRequest
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.credentials import NautobotCredentials


@pytest.mark.parametrize(
    "model",
    [
        NautobotTestConnectionRequest,
        PyATSTestConnectionRequest,
        MattermostTestConnectionRequest,
        ISETestConnectionRequest,
    ],
)
class TestTestConnectionRequestXor:
    def test_source_id_only_ok(self, model) -> None:
        assert model(source_id="lab").source_id == "lab"

    def test_inline_ok(self, model) -> None:
        req = model(url="https://x", credential_id=5)
        assert req.credential_id == 5

    def test_neither_rejected(self, model) -> None:
        with pytest.raises(ValidationError):
            model()

    def test_both_rejected(self, model) -> None:
        with pytest.raises(ValidationError):
            model(source_id="lab", url="https://x", credential_id=5)

    def test_url_without_credential_rejected(self, model) -> None:
        with pytest.raises(ValidationError):
            model(url="https://x")


class NautobotTestConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_when_status_returns_data(self) -> None:
        from services.nautobot.client import NautobotService

        service = NautobotService()
        service.rest_request = AsyncMock(return_value={"nautobot-version": "2.3.0"})
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


class ValidateGitRemoteUrlTests(unittest.TestCase):
    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_https(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        result = validate_git_remote_url("https://git.example.com/org/repo.git")
        self.assertEqual(result, "https://git.example.com/org/repo.git")

    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_scp_like_syntax(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        result = validate_git_remote_url("git@git.example.com:org/repo.git")
        self.assertEqual(result, "git@git.example.com:org/repo.git")

    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_ssh_scheme(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        result = validate_git_remote_url("ssh://git@git.example.com/org/repo.git")
        self.assertEqual(result, "ssh://git@git.example.com/org/repo.git")

    def test_rejects_file_scheme(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("file:///tmp/repo.git")

    def test_rejects_http_scheme_in_production(self) -> None:
        with patch("core.safe_urls.settings.environment", "production"):
            with self.assertRaises(UnsafeURLError):
                validate_git_remote_url("http://git.example.com/org/repo.git")

    @patch("core.safe_urls.socket.getaddrinfo")
    def test_allows_http_scheme_in_development(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
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
