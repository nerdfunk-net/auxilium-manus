"""Tests for Netmiko platform mapping."""

from __future__ import annotations

import unittest

from services.network.netmiko.platform import resolve_netmiko_device_type


class NetmikoPlatformTests(unittest.TestCase):
    def test_resolve_known_driver(self) -> None:
        self.assertEqual(
            resolve_netmiko_device_type(network_driver="cisco_ios", platform=None),
            "cisco_ios",
        )

    def test_resolve_platform_alias(self) -> None:
        self.assertEqual(
            resolve_netmiko_device_type(network_driver=None, platform="junos"),
            "juniper_junos",
        )

    def test_resolve_unknown_defaults_to_cisco_ios(self) -> None:
        self.assertEqual(
            resolve_netmiko_device_type(network_driver="unknown-vendor", platform=None),
            "cisco_ios",
        )


if __name__ == "__main__":
    unittest.main()
