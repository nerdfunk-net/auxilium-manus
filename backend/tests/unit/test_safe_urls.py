"""Tests for outbound HTTP URL policy (M3)."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from core.safe_urls import UnsafeURLError, validate_git_remote_url, validate_outbound_http_url


def _addrinfo(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


class SafeUrlsTests(unittest.TestCase):
    def test_https_hostname_ok(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("203.0.113.10")):
            result = validate_outbound_http_url("https://nautobot.example.com/")
        self.assertEqual(result, "https://nautobot.example.com")

    def test_rfc1918_literal_ok(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            result = validate_outbound_http_url("https://10.0.0.5")
        self.assertEqual(result, "https://10.0.0.5")

    def test_rejects_link_local_metadata(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_outbound_http_url("http://169.254.169.254/", resolve_dns=False)

    def test_rejects_loopback_by_default(self) -> None:
        with patch("core.safe_urls.settings") as settings_mock:
            settings_mock.allow_loopback_source_urls = False
            with self.assertRaises(UnsafeURLError):
                validate_outbound_http_url("https://127.0.0.1", resolve_dns=False)

    def test_allows_loopback_when_flag_set(self) -> None:
        with patch("core.safe_urls.settings") as settings_mock:
            settings_mock.allow_loopback_source_urls = True
            with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
                result = validate_outbound_http_url("https://127.0.0.1")
        self.assertEqual(result, "https://127.0.0.1")

    def test_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_outbound_http_url("ftp://x.example.com", resolve_dns=False)

    def test_rejects_userinfo(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_outbound_http_url("https://user:pass@host.example.com/", resolve_dns=False)

    def test_rejects_blocked_metadata_hostname(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_outbound_http_url("http://metadata.google.internal/", resolve_dns=False)

    def test_rejects_dns_resolving_to_link_local(self) -> None:
        with patch(
            "core.safe_urls.socket.getaddrinfo",
            return_value=_addrinfo("169.254.169.254"),
        ):
            with self.assertRaises(UnsafeURLError):
                validate_outbound_http_url("https://evil.example.com")


class GitRemoteUrlSshPolicyTests(unittest.TestCase):
    """SSH/scp-like git remotes must go through the same IP policy as https (H2)."""

    def test_ssh_url_public_dns_ok(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("203.0.113.10")):
            result = validate_git_remote_url("ssh://git@git.example.com/org/repo.git")
        self.assertEqual(result, "ssh://git@git.example.com/org/repo.git")

    def test_ssh_url_literal_link_local_blocked(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url(
                "ssh://git@169.254.169.254/org/repo.git", resolve_dns=False
            )

    def test_ssh_url_loopback_blocked_by_default(self) -> None:
        with patch("core.safe_urls.settings") as settings_mock:
            settings_mock.allow_loopback_source_urls = False
            with self.assertRaises(UnsafeURLError):
                validate_git_remote_url("ssh://git@127.0.0.1/org/repo.git", resolve_dns=False)

    def test_scp_like_literal_link_local_blocked(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("git@169.254.169.254:org/repo.git", resolve_dns=False)

    def test_scp_like_rfc1918_dns_allowed(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            result = validate_git_remote_url("git@git.example.com:org/repo.git")
        self.assertEqual(result, "git@git.example.com:org/repo.git")

    def test_ssh_url_blocked_metadata_hostname(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url(
                "ssh://git@metadata.google.internal/org/repo.git", resolve_dns=False
            )


class ClientUrlValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ise_ers_request_validates_before_httpx(self) -> None:
        from services.ise.client import ISEService
        from services.ise.common.exceptions import ISEValidationError
        from services.ise.credentials import ISECredentials

        service = ISEService()
        service._client_verify = MagicMock()
        with patch(
            "services.ise.client.validate_outbound_http_url",
            side_effect=UnsafeURLError("blocked"),
        ) as validate_mock:
            with self.assertRaises(ISEValidationError):
                await service.ers_request(
                    "networkdevice",
                    ISECredentials(
                        base_url="http://169.254.169.254",
                        username="u",
                        password="p",
                    ),
                )
            validate_mock.assert_called_once()
            service._client_verify.request.assert_not_called()

    async def test_nautobot_graphql_validates_before_httpx(self) -> None:
        from services.nautobot.client import NautobotService
        from services.nautobot.common.exceptions import NautobotValidationError
        from services.nautobot.credentials import NautobotCredentials

        service = NautobotService()
        service._client_verify = MagicMock()
        with patch(
            "services.nautobot.client.validate_outbound_http_url",
            side_effect=UnsafeURLError("blocked"),
        ) as validate_mock:
            with self.assertRaises(NautobotValidationError):
                await service.graphql_query(
                    "{ devices { id } }",
                    None,
                    NautobotCredentials(url="http://169.254.169.254", token="tok"),
                )
            validate_mock.assert_called_once()
            service._client_verify.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
