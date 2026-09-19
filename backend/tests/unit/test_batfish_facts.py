"""Tests for workflow_steps/config_to_attributes/batfish_facts.py."""

from __future__ import annotations

import unittest

from workflow_steps.config_to_attributes.batfish_facts import (
    build_layer3_interfaces_from_batfish_facts,
)


def _node_facts(interfaces: dict) -> dict:
    return {"Interfaces": interfaces}


class BuildLayer3InterfacesFromBatfishFactsTests(unittest.TestCase):
    def test_primary_and_secondary_ip(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "All_Prefixes": ["192.168.178.120/24", "192.168.178.240/24"],
                    "Description": "xxx",
                    "MTU": 1500,
                    "Primary_Address": "192.168.178.240/24",
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(len(interfaces), 1)
        iface = interfaces[0]
        self.assertEqual(iface["name"], "Ethernet0/0")
        self.assertEqual(iface["description"], "xxx")
        self.assertEqual(iface["mtu"], 1500)
        self.assertEqual(
            iface["ip_addresses"],
            [
                {
                    "address": "192.168.178.240/24",
                    "namespace": "Global",
                    "is_primary": True,
                },
                {
                    "address": "192.168.178.120/24",
                    "namespace": "Global",
                    "ip_role": "secondary",
                },
            ],
        )

    def test_no_prefixes_omits_ip_addresses(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/2": {
                    "Active": False,
                    "Admin_Up": False,
                    "All_Prefixes": [],
                    "Description": "test",
                    "MTU": 1500,
                    "Primary_Address": None,
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertNotIn("ip_addresses", interfaces[0])

    def test_status_always_active_regardless_of_batfish_active_flag(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {"Active": True, "Admin_Up": True},
                "Ethernet0/1": {"Active": False, "Admin_Up": False},
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        for iface in interfaces:
            self.assertEqual(iface["status"], "Active")

    def test_enabled_derived_from_admin_up_independent_of_active(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {"Active": True, "Admin_Up": True},
                "Ethernet0/1": {"Active": False, "Admin_Up": False},
                "Ethernet0/2": {"Active": False, "Admin_Up": True},
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Ethernet0/0"]["enabled"])
        self.assertFalse(by_name["Ethernet0/1"]["enabled"])
        self.assertTrue(by_name["Ethernet0/2"]["enabled"])

    def test_access_switchport_sets_mode_and_untagged_vlan(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "Access_VLAN": 100,
                    "Switchport": True,
                    "Switchport_Mode": "ACCESS",
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(interfaces[0]["mode"], "access")
        self.assertEqual(interfaces[0]["untagged_vlan"], 100)

    def test_routed_interface_no_mode_or_untagged_vlan(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "Access_VLAN": None,
                    "Switchport": False,
                    "Switchport_Mode": "NONE",
                    "All_Prefixes": ["192.168.1.1/24"],
                    "Primary_Address": "192.168.1.1/24",
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertNotIn("mode", interfaces[0])
        self.assertNotIn("untagged_vlan", interfaces[0])

    def test_access_switchport_with_no_vlan_omits_mode(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "Access_VLAN": None,
                    "Switchport": True,
                    "Switchport_Mode": "ACCESS",
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertNotIn("mode", interfaces[0])
        self.assertNotIn("untagged_vlan", interfaces[0])

    def test_trunk_switchport_not_handled(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "Access_VLAN": None,
                    "Switchport": True,
                    "Switchport_Mode": "TRUNK",
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertNotIn("mode", interfaces[0])
        self.assertNotIn("untagged_vlan", interfaces[0])

    def test_channel_group_sets_lag(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/2": {
                    "Active": True,
                    "Admin_Up": True,
                    "Channel_Group": "Port-channel10",
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(interfaces[0]["lag"], "Port-channel10")

    def test_no_channel_group_omits_lag(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/2": {
                    "Active": True,
                    "Admin_Up": True,
                    "Channel_Group": None,
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertNotIn("lag", interfaces[0])

    def test_port_channel_interface_gets_lag_type(self) -> None:
        node_facts = _node_facts(
            {
                "Port-channel10": {
                    "Active": True,
                    "Admin_Up": True,
                    "Channel_Group": None,
                    "Channel_Group_Members": ["Ethernet0/2"],
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(interfaces[0]["type"], "lag")
        self.assertNotIn("lag", interfaces[0])

    def test_switchport_with_no_l3_data_still_included(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "Access_VLAN": 100,
                    "Switchport": True,
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(len(interfaces), 1)
        self.assertEqual(interfaces[0]["name"], "Ethernet0/0")
        self.assertNotIn("ip_addresses", interfaces[0])

    def test_blacklisted_interface_still_included(self) -> None:
        node_facts = _node_facts(
            {
                "Ethernet0/3": {
                    "Active": False,
                    "Admin_Up": False,
                    "Blacklisted": True,
                    "All_Prefixes": [],
                }
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        self.assertEqual(len(interfaces), 1)

    def test_interface_type_inferred_from_name(self) -> None:
        node_facts = _node_facts(
            {
                "GigabitEthernet0/1": {"Active": True, "Admin_Up": True},
                "Ethernet0/0": {"Active": True, "Admin_Up": True},
                "Vlan100": {"Active": True, "Admin_Up": True},
            }
        )
        interfaces = build_layer3_interfaces_from_batfish_facts(node_facts)
        by_name = {i["name"]: i for i in interfaces}
        self.assertEqual(by_name["GigabitEthernet0/1"]["type"], "1000base-t")
        self.assertEqual(by_name["Ethernet0/0"]["type"], "100base-tx")
        self.assertEqual(by_name["Vlan100"]["type"], "virtual")

    def test_missing_interfaces_key_returns_empty_list(self) -> None:
        self.assertEqual(build_layer3_interfaces_from_batfish_facts({}), [])

    def test_non_dict_input_returns_empty_list(self) -> None:
        self.assertEqual(build_layer3_interfaces_from_batfish_facts(None), [])  # type: ignore[arg-type]
        self.assertEqual(build_layer3_interfaces_from_batfish_facts([]), [])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
