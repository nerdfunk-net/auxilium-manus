"""core/client_ip.py — trusted-proxy-aware client IP resolution (T1)."""

from __future__ import annotations

import unittest
from ipaddress import ip_network
from unittest.mock import patch

from starlette.requests import Request

from core.client_ip import is_trusted_proxy, resolve_client_host


def _request(client_host: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": raw_headers,
    }
    return Request(scope)


class ResolveClientHostTests(unittest.TestCase):
    def _networks(self, *cidrs: str):
        return frozenset(ip_network(cidr) for cidr in cidrs)

    def test_untrusted_direct_peer_with_xff_returns_direct_peer(self) -> None:
        with patch("core.client_ip.settings.trusted_proxy_networks", self._networks("10.0.0.0/8")):
            request = _request("203.0.113.50", {"x-forwarded-for": "1.2.3.4"})
            self.assertEqual(resolve_client_host(request), "203.0.113.50")

    def test_trusted_peer_with_single_xff_entry(self) -> None:
        with patch(
            "core.client_ip.settings.trusted_proxy_networks", self._networks("127.0.0.1/32")
        ):
            request = _request("127.0.0.1", {"x-forwarded-for": "203.0.113.9"})
            self.assertEqual(resolve_client_host(request), "203.0.113.9")

    def test_trusted_peer_picks_rightmost_non_trusted_entry(self) -> None:
        with patch("core.client_ip.settings.trusted_proxy_networks", self._networks("10.0.0.0/8")):
            request = _request(
                "10.0.0.1",
                {"x-forwarded-for": "198.51.100.7, 203.0.113.9, 10.0.0.2"},
            )
            self.assertEqual(resolve_client_host(request), "203.0.113.9")

    def test_trusted_peer_chain_entirely_trusted_returns_direct_peer(self) -> None:
        with patch("core.client_ip.settings.trusted_proxy_networks", self._networks("10.0.0.0/8")):
            request = _request("10.0.0.1", {"x-forwarded-for": "10.0.0.2, 10.0.0.3"})
            self.assertEqual(resolve_client_host(request), "10.0.0.1")

    def test_trusted_peer_malformed_rightmost_entry_falls_back_to_direct(self) -> None:
        with patch(
            "core.client_ip.settings.trusted_proxy_networks", self._networks("127.0.0.1/32")
        ):
            request = _request("127.0.0.1", {"x-forwarded-for": "203.0.113.9, evil"})
            self.assertEqual(resolve_client_host(request), "127.0.0.1")

    def test_trusted_peer_malformed_leftmost_entry_still_resolves_rightmost(self) -> None:
        with patch(
            "core.client_ip.settings.trusted_proxy_networks", self._networks("127.0.0.1/32")
        ):
            request = _request("127.0.0.1", {"x-forwarded-for": "evil, 203.0.113.9"})
            self.assertEqual(resolve_client_host(request), "203.0.113.9")

    def test_trusted_peer_no_xff_but_x_real_ip_is_ignored(self) -> None:
        with patch(
            "core.client_ip.settings.trusted_proxy_networks", self._networks("127.0.0.1/32")
        ):
            request = _request("127.0.0.1", {"x-real-ip": "203.0.113.9"})
            self.assertEqual(resolve_client_host(request), "127.0.0.1")

    def test_is_trusted_proxy_rejects_non_ip(self) -> None:
        with patch("core.client_ip.settings.trusted_proxy_networks", self._networks("10.0.0.0/8")):
            self.assertFalse(is_trusted_proxy("not-an-ip"))


if __name__ == "__main__":
    unittest.main()
