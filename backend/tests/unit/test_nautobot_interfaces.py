"""Tests for workflow_steps/common/nautobot_interfaces.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.nautobot_interfaces import interfaces_from_nautobot_bag


class InterfacesFromNautobotBagTests(unittest.TestCase):
    def test_enabled_true_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "enabled": True}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["enabled"], True)

    def test_enabled_false_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/2", "enabled": False}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["enabled"], False)

    def test_enabled_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("enabled", interfaces[0])

    def test_enabled_omitted_when_not_bool(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "enabled": "yes"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("enabled", interfaces[0])

    def test_empty_bag_returns_empty_list(self) -> None:
        self.assertEqual(interfaces_from_nautobot_bag(None, default_prefix_length="/24"), [])
        self.assertEqual(interfaces_from_nautobot_bag({}, default_prefix_length="/24"), [])


if __name__ == "__main__":
    unittest.main()
