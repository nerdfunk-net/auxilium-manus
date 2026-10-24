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

    def test_nxos_ethernet_maps_to_1000base_t(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Ethernet1/1"), "1000base-t")

    def test_loopback_is_virtual(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Loopback0"), "virtual")

    def test_physical_names_get_physical_types(self) -> None:
        table = {
            "Port-channel10": "lag",
            "Po1": "lag",
            "Vlan100": "virtual",
            "Tunnel0": "virtual",
            "Null0": "virtual",
            "FastEthernet0/1": "100base-tx",
            "GigabitEthernet1/0/1": "1000base-t",
            "Gi1/0/1": "1000base-t",
            "TenGigabitEthernet1/1/1": "10gbase-x-sfpp",
            "Te1/1/1": "10gbase-x-sfpp",
            "TwentyFiveGigE1/0/1": "25gbase-x-sfp28",
            "Twe1/0/1": "25gbase-x-sfp28",
            "FortyGigabitEthernet1/1/1": "40gbase-x-qsfpp",
            "Fo1/1/1": "40gbase-x-qsfpp",
            "HundredGigE1/0/1": "100gbase-x-qsfp28",
            "Hu1/0/1": "100gbase-x-qsfp28",
            "mgmt0": "1000base-t",
            "Management0/0": "1000base-t",
        }
        for name, expected in table.items():
            with self.subTest(name=name):
                self.assertEqual(infer_interface_type_from_name(name), expected)

    def test_unknown_name_is_other_not_virtual(self) -> None:
        self.assertEqual(infer_interface_type_from_name("Serial0/0/0"), "other")
        self.assertEqual(infer_interface_type_from_name("1/1"), "other")


class InterfacesFromNautobotBagTests(unittest.TestCase):
    def test_ip_namespace_from_parent_namespace_name(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "eth0",
                        "ip_addresses": [
                            {
                                "address": "10.0.0.1/24",
                                "parent": {"namespace": {"name": "black"}},
                            }
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["namespace"], "black")

    def test_ip_namespace_object_on_the_ip_is_read(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "eth0",
                        "ip_addresses": [
                            {"address": "10.0.0.1/24", "namespace": {"name": "black"}}
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["namespace"], "black")

    def test_ip_namespace_plain_string_is_read(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "eth0",
                        "ip_addresses": [{"address": "10.0.0.1/24", "namespace": "red"}],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["namespace"], "red")

    def test_ip_namespace_defaults_to_global(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "eth0", "ip_addresses": [{"address": "10.0.0.1/24"}]}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["namespace"], "Global")

    def test_ip_namespace_blank_parent_falls_back_to_global(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "eth0",
                        "ip_addresses": [
                            {"address": "10.0.0.1/24", "parent": {"namespace": {"name": " "}}}
                        ],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["ip_addresses"][0]["namespace"], "Global")

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

    def test_tagged_vlans_int_list_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/4", "tagged_vlans": [10, 20, 30]}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["tagged_vlans"], [10, 20, 30])

    def test_tagged_vlans_uuid_list_passes_through(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/4",
                        "tagged_vlans": ["3542814a-d33f-4cc3-bfdd-eb3a35945b31"],
                    }
                ]
            },
            default_prefix_length="/24",
        )
        self.assertEqual(
            interfaces[0]["tagged_vlans"], ["3542814a-d33f-4cc3-bfdd-eb3a35945b31"]
        )

    def test_tagged_vlans_omitted_when_missing(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/4"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("tagged_vlans", interfaces[0])

    def test_tagged_vlans_omitted_when_empty_list(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/4", "tagged_vlans": []}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("tagged_vlans", interfaces[0])

    def test_tagged_vlans_omitted_when_not_a_list(self) -> None:
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "Ethernet0/4", "tagged_vlans": "10,20"}]},
            default_prefix_length="/24",
        )
        self.assertNotIn("tagged_vlans", interfaces[0])


if __name__ == "__main__":
    unittest.main()
