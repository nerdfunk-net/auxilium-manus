"""Unit tests for the Netmiko template-preview host policy."""

from __future__ import annotations

import unittest

from core.safe_hosts import validate_netmiko_preview_host


class ValidateNetmikoPreviewHostTests(unittest.TestCase):
    def test_development_allows_rfc1918_host(self) -> None:
        result = validate_netmiko_preview_host(
            "10.1.2.3", environment="development", allow_arbitrary=False
        )
        self.assertEqual(result, "10.1.2.3")

    def test_rejects_metadata_literal_ip(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "169.254.169.254", environment="development", allow_arbitrary=True
            )

    def test_rejects_metadata_hostname(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "metadata.google.internal", environment="development", allow_arbitrary=True
            )

    def test_rejects_loopback(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "127.0.0.1", environment="development", allow_arbitrary=True
            )

    def test_production_rejects_arbitrary_host_by_default(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "10.1.2.3", environment="production", allow_arbitrary=False
            )

    def test_production_allows_host_when_arbitrary_enabled(self) -> None:
        result = validate_netmiko_preview_host(
            "10.1.2.3", environment="production", allow_arbitrary=True
        )
        self.assertEqual(result, "10.1.2.3")

    def test_rejects_empty_host(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host("", environment="development", allow_arbitrary=True)


if __name__ == "__main__":
    unittest.main()
