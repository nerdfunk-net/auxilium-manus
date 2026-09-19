"""Tests for workflow_steps/common/nautobot_interfaces.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.nautobot_interfaces import (
    infer_interface_type_from_name,
    interfaces_from_nautobot_bag,
)


class InferInterfaceTypeFromNameTests(unittest.TestCase):
    def test_port_channel_maps_to_lag(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Port-channel10"), "lag")

    def test_port_channel_case_insensitive(self) -> None:
        self.assertEqual(infer_interface_type_from_name("port-channel1"), "lag")
        self.assertEqual(infer_interface_type_from_name("PORT-CHANNEL2"), "lag")

    def test_gigabit_maps_to_1000base_t(self) -> None:
        self.assertEqual(infer_interface_type_from_name("GigabitEthernet0/1"), "1000base-t")

    def test_ethernet_maps_to_100base_tx(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Ethernet0/0"), "100base-tx")

    def test_unknown_defaults_to_virtual(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Loopback0"), "virtual")


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

    def test_mtu_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "mtu": 1500}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["mtu"], 1500)

    def test_mtu_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("mtu", interfaces[0])

    def test_mtu_omitted_when_not_int(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "mtu": "1500"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("mtu", interfaces[0])

    def test_mode_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "mode": "access"}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["mode"], "access")

    def test_mode_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("mode", interfaces[0])

    def test_untagged_vlan_int_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "untagged_vlan": 100}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["untagged_vlan"], 100)

    def test_untagged_vlan_uuid_string_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {"name": "Ethernet0/0", "untagged_vlan": "3542814a-d33f-4cc3-bfdd-eb3a35945b31"}
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["untagged_vlan"], "3542814a-d33f-4cc3-bfdd-eb3a35945b31")

    def test_untagged_vlan_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("untagged_vlan", interfaces[0])

    def test_untagged_vlan_omitted_when_none_sentinel(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/0", "untagged_vlan": "none"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("untagged_vlan", interfaces[0])

    def test_lag_name_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/2", "lag": "Port-channel10"}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["lag"], "Port-channel10")

    def test_lag_uuid_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {"name": "Ethernet0/2", "lag": "3542814a-d33f-4cc3-bfdd-eb3a35945b31"}
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["lag"], "3542814a-d33f-4cc3-bfdd-eb3a35945b31")

    def test_lag_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/2"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("lag", interfaces[0])

    def test_lag_omitted_when_none_sentinel(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/2", "lag": "none"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("lag", interfaces[0])


if __name__ == "__main__":
    unittest.main()
