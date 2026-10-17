"""Tests for Netmiko platform mapping."""

from __future__ import annotations

import unittest

from services.network.netmiko.platform import (
    UnsupportedPlatformError,
    resolve_connection_device_type,
    resolve_netmiko_device_type,
)


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

    def test_unknown_platform_raises(self) -> None:
        with self.assertRaises(UnsupportedPlatformError) as ctx:
            resolve_netmiko_device_type(network_driver="unknown-vendor", platform=None)
        self.assertEqual(ctx.exception.failure.kind, "unsupported_platform")
        self.assertEqual(ctx.exception.failure.hint, "check_platform")
        with self.assertRaises(UnsupportedPlatformError):
            resolve_netmiko_device_type(network_driver=None, platform=None)

    def test_iosxr_variants_are_not_ios(self) -> None:
        for value in ("cisco_iosxr", "Cisco IOS XR", "ios-xr", "iosxr"):
            self.assertEqual(
                resolve_netmiko_device_type(network_driver=None, platform=value), "cisco_xr", value
            )

    def test_netmiko_native_names_resolve(self) -> None:
        for name in ("fortinet", "huawei", "mikrotik_routeros", "aruba_aoscx"):
            self.assertEqual(
                resolve_netmiko_device_type(network_driver=None, platform=name), name
            )

    def test_substring_no_longer_maps(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            resolve_netmiko_device_type(network_driver=None, platform="hpe_aruba_aoscx_x")

    def test_telnet_never_chosen_automatically(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            resolve_netmiko_device_type(network_driver=None, platform="cisco_ios_telnet")
        # an explicit override stays the escape hatch
        self.assertEqual(
            resolve_connection_device_type(
                network_driver=None, platform=None, override="cisco_ios_telnet"
            ),
            "cisco_ios_telnet",
        )

    def test_connection_override_maps_alias(self) -> None:
        self.assertEqual(
            resolve_connection_device_type(
                network_driver="junos",
                platform=None,
                override="ios",
            ),
            "cisco_ios",
        )

    def test_connection_override_passthrough(self) -> None:
        self.assertEqual(
            resolve_connection_device_type(
                network_driver=None,
                platform=None,
                override="cisco_nxos",
            ),
            "cisco_nxos",
        )


if __name__ == "__main__":
    unittest.main()
