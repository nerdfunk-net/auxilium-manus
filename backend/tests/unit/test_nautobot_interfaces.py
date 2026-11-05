"""Tests for workflow_steps/common/nautobot_interfaces.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    infer_interface_type_from_name,
    interfaces_from_nautobot_bag,
    interfaces_from_parsed_list,
    normalize_duplex,
    normalize_mac,
    normalize_mtu,
    normalize_speed_kbps,
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

    def test_mtu_string_is_converted_and_garbage_omitted(self) -> None:
        # update-attribute writes strings into the bag, so "1500" must be accepted
        interfaces = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "a", "mtu": "1500"}, {"name": "b", "mtu": "big"}]},
            default_prefix_length="/24",
        )
        self.assertEqual(interfaces[0]["mtu"], 1500)
        self.assertNotIn("mtu", interfaces[1])

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


class NormalizerTests(unittest.TestCase):
    def test_mac_formats(self) -> None:
        for raw in ("aabb.cc00.0100", "AA:BB:CC:00:01:00", "aa-bb-cc-00-01-00", "aabbcc000100"):
            self.assertEqual(normalize_mac(raw), "AA:BB:CC:00:01:00", raw)

    def test_mac_invalid_or_empty_is_none(self) -> None:
        for raw in ("", None, "  ", "aabb.cc00", "zzzz.zzzz.zzzz", 12, "aabb.cc00.0100.0000"):
            self.assertIsNone(normalize_mac(raw), raw)

    def test_speed_to_kbps(self) -> None:
        cases = {
            "10000 Kbit": 10000,
            "1000Mb/s": 1_000_000,
            "100 Mbit": 100_000,
            "1 Gbit": 1_000_000,
            "10Gb/s": 10_000_000,
            "1000": 1000,
            1000: 1000,
            "2.5 Gbit": 2_500_000,
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_speed_kbps(raw), expected, raw)

    def test_speed_invalid_is_none(self) -> None:
        for raw in ("", None, "auto", "fast", -5, True, "0"):
            self.assertIsNone(normalize_speed_kbps(raw), raw)

    def test_duplex(self) -> None:
        self.assertEqual(normalize_duplex("Full-duplex"), "full")
        self.assertEqual(normalize_duplex("a-full"), "full")
        self.assertEqual(normalize_duplex("HALF"), "half")
        self.assertEqual(normalize_duplex("auto"), "auto")
        self.assertIsNone(normalize_duplex(""))
        self.assertIsNone(normalize_duplex("weird"))
        self.assertIsNone(normalize_duplex(None))

    def test_mtu(self) -> None:
        self.assertEqual(normalize_mtu("1500"), 1500)
        self.assertEqual(normalize_mtu(9000), 9000)
        for raw in ("", None, "abc", 0, "0", -1, True):
            self.assertIsNone(normalize_mtu(raw), raw)


class ConfigAndBagNewFieldTests(unittest.TestCase):
    def test_config_passes_and_normalizes_new_fields(self) -> None:
        [iface] = build_interfaces_from_config(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "mac_address": "aabb.cc00.0100",
                        "port_type": "8P8C",
                        "mode": "Access",
                        "speed": "1 Gbit",
                        "duplex": "Full",
                        "mtu": "1500",
                        "vrf": "MGMT",
                    }
                ]
            },
            step_id="t",
        )
        self.assertEqual(
            iface,
            {
                "name": "Ethernet0/0",
                "mac_address": "AA:BB:CC:00:01:00",
                "port_type": "8p8c",
                "mode": "access",
                "speed": 1_000_000,
                "duplex": "full",
                "mtu": 1500,
                "vrf": "MGMT",
            },
        )

    def test_config_drops_invalid_values(self) -> None:
        [iface] = build_interfaces_from_config(
            {"interfaces": [{"name": "e0", "mac_address": "nope", "speed": "fast"}]},
            step_id="t",
        )
        self.assertEqual(iface, {"name": "e0"})

    def test_bag_passes_new_fields(self) -> None:
        bag = {
            "interfaces": [
                {
                    "name": "Ethernet0/0",
                    "mac_address": "AA:BB:CC:00:01:00",
                    "port_type": "8p8c",
                    "speed": 1000,
                    "duplex": "full",
                    "vrf": {"name": "MGMT"},
                }
            ]
        }
        [iface] = interfaces_from_nautobot_bag(bag, default_prefix_length="/24")
        self.assertEqual(iface["mac_address"], "AA:BB:CC:00:01:00")
        self.assertEqual(iface["port_type"], "8p8c")
        self.assertEqual(iface["speed"], 1000)
        self.assertEqual(iface["duplex"], "full")
        self.assertEqual(iface["vrf"], "MGMT")

    def test_bag_without_new_fields_is_unchanged(self) -> None:
        [iface] = interfaces_from_nautobot_bag(
            {"interfaces": [{"name": "e0"}]}, default_prefix_length="/24"
        )
        self.assertEqual(iface, {"name": "e0"})


class InterfacesFromParsedListTests(unittest.TestCase):
    ROWS = [
        {"interface": "Ethernet0/0", "mac_address": "aabb.cc00.0100", "mtu": "1500",
         "speed": "10000 Kbit", "duplex": ""},
        {"interface": "Loopback0", "mac_address": "", "mtu": "1514", "speed": "", "duplex": ""},
        {"interface": "", "mac_address": "aabb.cc00.0999"},
        "not a row",
    ]
    FIELD_MAP = {
        "name": "interface",
        "mac_address": "mac_address",
        "mtu": "mtu",
        "speed": "speed",
        "duplex": "duplex",
    }

    def test_maps_columns_and_skips_blank_values_and_nameless_rows(self) -> None:
        result = interfaces_from_parsed_list(self.ROWS, self.FIELD_MAP)
        self.assertEqual(
            result,
            [
                {"name": "Ethernet0/0", "mac_address": "AA:BB:CC:00:01:00", "mtu": 1500,
                 "speed": 10000},
                {"name": "Loopback0", "mtu": 1514},
            ],
        )

    def test_name_mapping_is_required(self) -> None:
        with self.assertRaises(ValueError):
            interfaces_from_parsed_list(self.ROWS, {"mac_address": "mac_address"})

    def test_unmapped_fields_are_ignored(self) -> None:
        result = interfaces_from_parsed_list(self.ROWS, {"name": "interface"})
        self.assertEqual(result, [{"name": "Ethernet0/0"}, {"name": "Loopback0"}])

    def test_non_list_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            interfaces_from_parsed_list({"a": 1}, self.FIELD_MAP)

    def test_blank_cell_keeps_the_fixed_value_and_a_filled_cell_overrides_it(self) -> None:
        rows = [{"interface": "e0", "vrf": ""}, {"interface": "e1", "vrf": "RED"}]
        result = interfaces_from_parsed_list(
            rows, {"name": "interface", "vrf": "vrf"}, fixed_values={"vrf": "MGMT"}
        )
        self.assertEqual([r["vrf"] for r in result], ["MGMT", "RED"])

    def test_cell_missing_from_the_row_keeps_the_fixed_value(self) -> None:
        result = interfaces_from_parsed_list(
            [{"interface": "e0"}],
            {"name": "interface", "duplex": "duplex"},
            fixed_values={"duplex": "full"},
        )
        self.assertEqual(result[0]["duplex"], "full")

    def test_non_string_description_and_type_cells_are_dropped(self) -> None:
        sealed = {"__sealed__": "xyz"}
        rows = [
            {"interface": "e0", "d": sealed, "t": 5},
            {"interface": "e1", "d": ["a"], "t": {"x": 1}},
            {"interface": "e2", "d": " uplink ", "t": " 10GBASE-T "},
        ]
        result = interfaces_from_parsed_list(
            rows, {"name": "interface", "description": "d", "type": "t"}
        )
        self.assertEqual(result[0], {"name": "e0"})
        self.assertEqual(result[1], {"name": "e1"})
        self.assertEqual(result[2], {"name": "e2", "description": "uplink", "type": "10gbase-t"})

    def test_new_type_infer_sets_type_if_new_from_the_name(self) -> None:
        rows = [{"interface": "Ethernet0/0"}, {"interface": "Loopback0"}, {"interface": "Foo9"}]
        result = interfaces_from_parsed_list(rows, {"name": "interface"}, new_type_mode="infer")
        self.assertEqual(
            [(r["name"], r["type_if_new"]) for r in result],
            [("Ethernet0/0", "1000base-t"), ("Loopback0", "virtual"), ("Foo9", "other")],
        )
        self.assertTrue(all("type" not in r for r in result))

    def test_new_type_fixed_sets_type_if_new_for_every_row(self) -> None:
        rows = [{"interface": "Ethernet0/0"}, {"interface": "Loopback0"}]
        result = interfaces_from_parsed_list(
            rows, {"name": "interface"}, new_type_mode="fixed", new_type_value=" Virtual "
        )
        self.assertEqual([r["type_if_new"] for r in result], ["virtual", "virtual"])
        self.assertTrue(all("type" not in r for r in result))

    def test_new_type_none_adds_nothing(self) -> None:
        result = interfaces_from_parsed_list(
            [{"interface": "Ethernet0/0"}], {"name": "interface"}, new_type_mode="none"
        )
        self.assertEqual(result, [{"name": "Ethernet0/0"}])

    def test_new_type_does_not_replace_an_explicit_type(self) -> None:
        result = interfaces_from_parsed_list(
            [{"interface": "Ethernet0/0", "t": "10gbase-t"}],
            {"name": "interface", "type": "t"},
            new_type_mode="infer",
        )
        self.assertEqual(result[0]["type"], "10gbase-t")
        self.assertEqual(result[0]["type_if_new"], "1000base-t")

    def test_new_type_fixed_without_value_is_an_error_and_unknown_mode_too(self) -> None:
        with self.assertRaises(ValueError):
            interfaces_from_parsed_list(
                [{"interface": "e0"}],
                {"name": "interface"},
                new_type_mode="fixed",
                new_type_value=" ",
            )
        with self.assertRaises(ValueError):
            interfaces_from_parsed_list(
                [{"interface": "e0"}], {"name": "interface"}, new_type_mode="bogus"
            )

    def test_literal_type_and_mode_values_via_constants(self) -> None:
        result = interfaces_from_parsed_list(
            self.ROWS[:1], self.FIELD_MAP, fixed_values={"type": "1000base-t", "mode": "Access"}
        )
        self.assertEqual(result[0]["type"], "1000base-t")
        self.assertEqual(result[0]["mode"], "access")


if __name__ == "__main__":
    unittest.main()
