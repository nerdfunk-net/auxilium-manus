"""Tests for services.network.pyats.platform.resolve_pyats_os."""

from __future__ import annotations

import unittest

from services.network.pyats.platform import resolve_pyats_os


class ResolvePyatsOsTests(unittest.TestCase):
    def test_maps_netmiko_style_network_driver(self) -> None:
        self.assertEqual(resolve_pyats_os(network_driver="cisco_ios", platform=None), "ios")
        self.assertEqual(resolve_pyats_os(network_driver="cisco_xe", platform=None), "iosxe")
        self.assertEqual(resolve_pyats_os(network_driver="cisco_nxos", platform=None), "nxos")
        self.assertEqual(resolve_pyats_os(network_driver="cisco_xr", platform=None), "iosxr")
        self.assertEqual(resolve_pyats_os(network_driver="juniper_junos", platform=None), "junos")
        self.assertEqual(resolve_pyats_os(network_driver="arista_eos", platform=None), "eos")

    def test_falls_back_to_platform_when_network_driver_missing(self) -> None:
        self.assertEqual(resolve_pyats_os(network_driver=None, platform="nxos"), "nxos")

    def test_override_takes_precedence(self) -> None:
        self.assertEqual(
            resolve_pyats_os(network_driver="cisco_ios", platform=None, override="junos"),
            "junos",
        )

    def test_unmapped_override_passes_through_lowercased(self) -> None:
        self.assertEqual(
            resolve_pyats_os(network_driver=None, platform=None, override="SomeCustomOs"),
            "somecustomos",
        )

    def test_unknown_defaults_to_ios(self) -> None:
        self.assertEqual(resolve_pyats_os(network_driver=None, platform=None), "ios")
        self.assertEqual(resolve_pyats_os(network_driver="totally-unknown", platform=None), "ios")


if __name__ == "__main__":
    unittest.main()
