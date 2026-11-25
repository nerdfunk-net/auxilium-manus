"""HSRP / VRRP redundancy groups built from Genie's running-config tree."""

from __future__ import annotations

import json
import unittest

from workflow_steps.common.interface_payload import (
    interfaces_from_nautobot_bag,
)
from workflow_steps.config_to_attributes.genie_running_config import (
    build_interfaces_from_genie_running_config,
)


def _build(tree: dict) -> dict[str, dict]:
    return {i["name"]: i for i in build_interfaces_from_genie_running_config(tree)}


class HsrpTests(unittest.TestCase):
    def test_user_vlan200_sample(self) -> None:
        iface = _build(
            {
                "interface Vlan200": {
                    "ip address 192.168.180.1 255.255.255.0": {},
                    "standby 0 ip 192.168.180.100": {},
                    "standby 0 priority 110": {},
                    "standby 0 preempt": {},
                    "standby 0 name HSRP-1": {},
                }
            }
        )["Vlan200"]
        self.assertEqual(
            iface["interface_redundancy_groups"],
            [
                {
                    "name": "HSRP-1",
                    "protocol": "HSRP",
                    "protocol_group_id": "0",
                    "virtual_ip": {"address": "192.168.180.100/24"},
                    "priority": 110,
                    "preempt": True,
                    "description": "HSRP-1",
                }
            ],
        )

    def test_no_standby_lines_means_no_key(self) -> None:
        iface = _build({"interface Vlan100": {"ip address 10.0.0.1 255.255.255.0": {}}})
        self.assertNotIn("interface_redundancy_groups", iface["Vlan100"])

    def test_two_groups_ordered_by_id(self) -> None:
        iface = _build(
            {
                "interface Vlan10": {
                    "ip address 10.1.0.2 255.255.255.0": {},
                    "standby 20 ip 10.1.0.20": {},
                    "standby 5 ip 10.1.0.5": {},
                }
            }
        )["Vlan10"]
        groups = iface["interface_redundancy_groups"]
        self.assertEqual([g["protocol_group_id"] for g in groups], ["5", "20"])

    def test_group_number_omitted_is_zero_and_name_falls_back(self) -> None:
        iface = _build(
            {
                "interface Vlan7": {
                    "ip address 10.7.0.2 255.255.255.0": {},
                    "standby ip 10.7.0.1": {},
                }
            }
        )["Vlan7"]
        group = iface["interface_redundancy_groups"][0]
        self.assertEqual(group["protocol_group_id"], "0")
        self.assertEqual(group["name"], "Vlan7-HSRP-0")
        self.assertNotIn("priority", group)
        self.assertFalse(group["preempt"])

    def test_group_without_virtual_ip_is_dropped(self) -> None:
        iface = _build({"interface Vlan8": {"standby 1 priority 120": {}}})["Vlan8"]
        self.assertNotIn("interface_redundancy_groups", iface)

    def test_secondary_virtual_ip_is_not_the_virtual_ip(self) -> None:
        iface = _build(
            {
                "interface Vlan9": {
                    "ip address 10.9.0.2 255.255.255.0": {},
                    "standby 1 ip 10.9.0.1": {},
                    "standby 1 ip 10.9.0.3 secondary": {},
                }
            }
        )["Vlan9"]
        self.assertEqual(
            iface["interface_redundancy_groups"][0]["virtual_ip"]["address"], "10.9.0.1/24"
        )

    def test_vip_outside_interface_subnet_stays_bare(self) -> None:
        iface = _build(
            {
                "interface Vlan11": {
                    "ip address 10.11.0.2 255.255.255.0": {},
                    "standby 1 ip 172.16.0.1": {},
                }
            }
        )["Vlan11"]
        self.assertEqual(
            iface["interface_redundancy_groups"][0]["virtual_ip"]["address"], "172.16.0.1"
        )

    def test_authentication_secret_is_never_copied(self) -> None:
        iface = _build(
            {
                "interface Vlan12": {
                    "ip address 10.12.0.2 255.255.255.0": {},
                    "standby 1 ip 10.12.0.1": {},
                    "standby 1 authentication md5 key-string SuperSecret123": {},
                }
            }
        )["Vlan12"]
        self.assertNotIn("SuperSecret123", json.dumps(iface))


class VrrpTests(unittest.TestCase):
    def test_legacy_vrrp_group(self) -> None:
        iface = _build(
            {
                "interface Vlan30": {
                    "ip address 10.30.0.2 255.255.255.0": {},
                    "vrrp 3 ip 10.30.0.1": {},
                    "vrrp 3 priority 90": {},
                    "vrrp 3 preempt": {},
                    "vrrp 3 description gateway": {},
                }
            }
        )["Vlan30"]
        group = iface["interface_redundancy_groups"][0]
        self.assertEqual(group["protocol"], "VRRP")
        self.assertEqual(group["protocol_group_id"], "3")
        self.assertEqual(group["priority"], 90)
        self.assertEqual(group["name"], "Vlan30-VRRP-3")
        self.assertEqual(group["description"], "gateway")
        self.assertEqual(group["virtual_ip"], {"address": "10.30.0.1/24"})

    def test_vrrp_description_reaches_the_write_path(self) -> None:
        built = _build(
            {
                "interface Vlan30": {
                    "ip address 10.30.0.2 255.255.255.0": {},
                    "vrrp 3 ip 10.30.0.1": {},
                    "vrrp 3 description gateway": {},
                }
            }
        )["Vlan30"]
        out = interfaces_from_nautobot_bag({"interfaces": [built]}, default_prefix_length="/24")
        self.assertEqual(out[0]["interface_redundancy_groups"][0]["description"], "gateway")

    def test_unsupported_vrrp_address_family_block_is_reported(self) -> None:
        from workflow_steps.config_to_attributes.genie_redundancy import (
            interfaces_with_unsupported_redundancy,
        )

        tree = {
            "interface Vlan30": {
                "vrrp 3 address-family ipv4": {"address 10.30.0.1 primary": {}},
            },
            "interface Vlan31": {"vrrp 1 ip 10.31.0.1": {}},
        }
        self.assertEqual(interfaces_with_unsupported_redundancy(tree), ["Vlan30"])


class ConsumerTests(unittest.TestCase):
    def test_update_path_reads_the_built_groups(self) -> None:
        built = _build(
            {
                "interface Vlan200": {
                    "ip address 192.168.180.1 255.255.255.0": {},
                    "standby 0 ip 192.168.180.100": {},
                    "standby 0 priority 110": {},
                    "standby 0 name HSRP-1": {},
                }
            }
        )["Vlan200"]
        out = interfaces_from_nautobot_bag({"interfaces": [built]}, default_prefix_length="/24")
        self.assertEqual(
            out[0]["interface_redundancy_groups"],
            [
                {
                    "protocol": "hsrp",
                    "protocol_group_id": "0",
                    "virtual_ip": {"address": "192.168.180.100/24"},
                    "description": "HSRP-1",
                    "namespace": "Global",
                    "priority": 110,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
