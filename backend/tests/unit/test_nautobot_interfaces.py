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

    def test_ip_role_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "ip_addresses": [
                            {"address": "10.0.0.1/24", "ip_role": "secondary"},
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["ip_role"], "secondary")

    def test_ip_role_omitted_when_none_sentinel(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "ip_addresses": [
                            {"address": "10.0.0.1/24", "ip_role": "none"},
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertNotIn("ip_role", interfaces[0]["ip_addresses"][0])

    def test_is_primary_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "ip_addresses": [
                            {"address": "10.0.0.1/24", "is_primary": True},
                            {"address": "10.0.0.2/24"},
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        addresses = interfaces[0]["ip_addresses"]
        self.assertEqual(addresses[0]["is_primary"], True)
        self.assertNotIn("is_primary", addresses[1])

    def test_string_ip_addresses_unaffected_by_role_lookup(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "ip_addresses": ["10.0.0.1"]}]},
            default_prefix_length="/24",
        )
        self.assertEqual(
            interfaces[0]["ip_addresses"], [{"address": "10.0.0.1/24", "namespace": "Global"}]
        )


if __name__ == "__main__":
    unittest.main()
