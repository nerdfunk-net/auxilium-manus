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


class ValidateDeviceHostTests(unittest.TestCase):
    """The sanity rules alone, for a host that came from the inventory (not typed by a user)."""

    def test_accepts_a_private_address_in_any_environment(self) -> None:
        from core.safe_hosts import validate_device_host

        self.assertEqual(validate_device_host(" 10.1.2.3 "), "10.1.2.3")
        self.assertEqual(validate_device_host("r1.example.net"), "r1.example.net")

    def test_rejects_the_same_hosts_as_the_preview_policy(self) -> None:
        from core.safe_hosts import validate_device_host

        for host in (
            "",
            "  ",
            "127.0.0.1",
            "169.254.169.254",
            "0.0.0.0",
            "224.0.0.1",
            "metadata.google.internal",
            "METADATA.GOOGLE.COM",
        ):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_device_host(host)

    def test_the_preview_policy_still_adds_the_arbitrary_host_rule_on_top(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "10.1.2.3", environment="production", allow_arbitrary=False
            )
