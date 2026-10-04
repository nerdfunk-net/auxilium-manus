"""Tests for outbound HTTP URL policy (M3)."""

from __future__ import annotations

import socket
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.safe_urls import (
    UnsafeURLError,
    validate_git_remote_url,
    validate_outbound_http_url,
    validate_outbound_http_url_async,
    validate_source_transport,
    validate_source_transport_async,
)


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


def _env(environment: str) -> SimpleNamespace:
    return SimpleNamespace(environment=environment, allow_loopback_source_urls=False)


class ValidateSourceTransportTests(unittest.TestCase):
    """Credential-bearing sources: https + verified TLS outside development."""

    def _validate(self, url: str, *, verify_ssl: bool, environment: str) -> str:
        with (
            patch("core.safe_urls.settings", _env(environment)),
            patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("203.0.113.10")),
        ):
            return validate_source_transport(url, verify_ssl=verify_ssl)

    def test_development_allows_http_and_unverified_tls(self) -> None:
        result = self._validate(
            "http://x.example.com/", verify_ssl=False, environment="development"
        )
        self.assertEqual(result, "http://x.example.com")

    def test_production_rejects_http(self) -> None:
        with self.assertRaisesRegex(UnsafeURLError, "https"):
            self._validate("http://x.example.com", verify_ssl=True, environment="production")

    def test_production_rejects_unverified_tls(self) -> None:
        with self.assertRaisesRegex(UnsafeURLError, "verify_ssl"):
            self._validate("https://x.example.com", verify_ssl=False, environment="production")

    def test_production_allows_https_with_verification(self) -> None:
        result = self._validate("https://x.example.com/", verify_ssl=True, environment="production")
        self.assertEqual(result, "https://x.example.com")

    def test_ssrf_rules_still_apply_in_development(self) -> None:
        with patch("core.safe_urls.settings", _env("development")):
            with self.assertRaises(UnsafeURLError):
                validate_source_transport(
                    "http://169.254.169.254/", verify_ssl=True, resolve_dns=False
                )


class ValidateSourceTransportAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_variant_applies_the_same_policy(self) -> None:
        with (
            patch("core.safe_urls.settings", _env("production")),
            patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("203.0.113.10")),
        ):
            with self.assertRaises(UnsafeURLError):
                await validate_source_transport_async("https://x.example.com", verify_ssl=False)
            result = await validate_source_transport_async("https://x.example.com", verify_ssl=True)
        self.assertEqual(result, "https://x.example.com")


class GitRemoteUrlSshPolicyTests(unittest.TestCase):
    """SSH/scp-like git remotes must go through the same IP policy as https (H2)."""

    def test_ssh_url_public_dns_ok(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("203.0.113.10")):
            result = validate_git_remote_url("ssh://git@git.example.com/org/repo.git")
        self.assertEqual(result, "ssh://git@git.example.com/org/repo.git")

    def test_ssh_url_literal_link_local_blocked(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("ssh://git@169.254.169.254/org/repo.git", resolve_dns=False)

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


class AsyncWrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_wrapper_offloads_and_normalizes(self) -> None:
        with patch("core.safe_urls.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            result = await validate_outbound_http_url_async("https://nautobot.example.com/")
        self.assertEqual(result, "https://nautobot.example.com")

    async def test_async_wrapper_rejects_metadata_host(self) -> None:
        with self.assertRaises(UnsafeURLError):
            await validate_outbound_http_url_async("http://169.254.169.254/")


class ClientUrlValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ise_ers_request_validates_before_httpx(self) -> None:
        from services.ise.client import ISEService
        from services.ise.common.exceptions import ISEValidationError
        from services.ise.credentials import ISECredentials

        service = ISEService()
        service._client_verify = MagicMock()
        with patch(
            "services.ise.client.validate_source_transport_async",
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
            "services.nautobot.client.validate_source_transport_async",
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
