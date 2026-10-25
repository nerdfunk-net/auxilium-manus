"""Tests for services/git/device_grouping.py (CSV simple + multi-line merge)."""

from __future__ import annotations

import copy
import unittest

from services.git.device_grouping import (
    map_single_row,
    map_single_row_with_problems,
    merge_device_rows,
)
from services.git.device_mapping import PRIMARY_FLAG_TARGET, MappingRule

RULES = [
    MappingRule("name", "name"),
    MappingRule("ip_address", "primary_ip4.address"),
    MappingRule("role", "role.name"),
    MappingRule("status", "status.name"),
    MappingRule("location", "location.name"),
    MappingRule("network_driver", "platform.network_driver"),
    MappingRule("interface_name", "interfaces.name"),
    MappingRule("interface_ip_address", "interfaces.ip_addresses.address"),
    MappingRule("cf_snmp", "custom_fields.snmp"),
]

CORE = {
    "name": "LAB",
    "ip_address": "192.168.178.240/24",
    "role": "network",
    "status": "Active",
    "location": "CityA",
    "network_driver": "cisco_ios",
}


def _row(**values: str) -> dict[str, str]:
    base = dict.fromkeys(
        [r.source for r in RULES],
        "",
    )
    return {**base, **values}


class MapSingleRowTests(unittest.TestCase):
    def test_simple_row_maps_device_attributes(self) -> None:
        mapped = map_single_row(_row(**CORE), RULES)
        self.assertEqual(mapped["name"], "LAB")
        self.assertEqual(mapped["location"], {"name": "CityA"})
        self.assertNotIn("interfaces", mapped)

    def test_row_with_interface_gets_single_item_list(self) -> None:
        mapped = map_single_row(
            _row(**CORE, interface_name="Eth0", interface_ip_address="10.0.0.1/24"), RULES
        )
        self.assertEqual(
            mapped["interfaces"],
            [{"name": "Eth0", "ip_addresses": [{"address": "10.0.0.1/24"}]}],
        )

    def test_row_without_name_is_none(self) -> None:
        self.assertIsNone(map_single_row(_row(role="x"), RULES))


class MergeDeviceRowsTests(unittest.TestCase):
    def _example_rows(self) -> list[dict[str, str]]:
        return [
            _row(**CORE),
            _row(
                name="LAB", interface_name="Ethernet0/0", interface_ip_address="192.168.178.240/24"
            ),
            _row(
                name="LAB", interface_name="Ethernet0/1", interface_ip_address="192.168.179.240/24"
            ),
        ]

    def test_example_merges_into_one_device_with_two_interfaces(self) -> None:
        groups, warnings = merge_device_rows(self._example_rows(), RULES)
        self.assertEqual(warnings, [])
        self.assertEqual(len(groups), 1)
        mapped = groups[0].mapped
        self.assertEqual(mapped["role"], {"name": "network"})
        self.assertEqual(mapped["platform"], {"network_driver": "cisco_ios"})
        self.assertEqual([i["name"] for i in mapped["interfaces"]], ["Ethernet0/0", "Ethernet0/1"])
        self.assertEqual(
            mapped["interfaces"][1]["ip_addresses"], [{"address": "192.168.179.240/24"}]
        )

    def test_later_non_empty_value_overwrites_earlier(self) -> None:
        rows = [_row(name="A", role="old", status="Active"), _row(name="A", role="new")]
        groups, _ = merge_device_rows(rows, RULES)
        self.assertEqual(groups[0].mapped["role"], {"name": "new"})
        self.assertEqual(groups[0].mapped["status"], {"name": "Active"})

    def test_empty_value_never_erases(self) -> None:
        rows = [_row(name="A", role="keep"), _row(name="A", role="")]
        groups, _ = merge_device_rows(rows, RULES)
        self.assertEqual(groups[0].mapped["role"], {"name": "keep"})
        self.assertEqual(groups[0].raw["role"], "keep")

    def test_first_seen_order_and_separate_devices(self) -> None:
        rows = [_row(name="B"), _row(name="A"), _row(name="B", role="x")]
        groups, _ = merge_device_rows(rows, RULES)
        self.assertEqual([g.mapped["name"] for g in groups], ["B", "A"])

    def test_nameless_rows_skipped_with_warning(self) -> None:
        groups, warnings = merge_device_rows([_row(name="A"), _row(role="x")], RULES)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("'name'", warnings[0])

    def test_custom_field_merged(self) -> None:
        rows = [_row(name="A"), _row(name="A", cf_snmp="public")]
        groups, _ = merge_device_rows(rows, RULES)
        self.assertEqual(groups[0].mapped["custom_fields"], {"snmp": "public"})

    def test_input_rows_not_mutated(self) -> None:
        rows = self._example_rows()
        snapshot = copy.deepcopy(rows)
        merge_device_rows(rows, RULES)
        self.assertEqual(rows, snapshot)


PRIMARY_RULES = [
    MappingRule("name", "name"),
    MappingRule("interface_name", "interfaces.name"),
    MappingRule("interface_address", "interfaces.ip_addresses.address"),
    MappingRule("namespace", "interfaces.ip_addresses.parent.namespace.name"),
    MappingRule("is_primary", PRIMARY_FLAG_TARGET),
]


def _prow(name: str, iface: str, address: str, primary: str, namespace: str = "") -> dict:
    return {
        "name": name,
        "interface_name": iface,
        "interface_address": address,
        "is_primary": primary,
        "namespace": namespace,
    }


class PrimaryIpTests(unittest.TestCase):
    def _merge(self, rows):
        groups, _ = merge_device_rows(rows, PRIMARY_RULES)
        return {g.mapped["name"]: g for g in groups}

    def test_flagged_interface_becomes_primary_ip4(self) -> None:
        by_name = self._merge(
            [
                _prow("device-1", "eth0", "10.0.0.2/24", "true", "black"),
                _prow("device-1", "eth1", "192.168.181.10/24", "false", "Global"),
            ]
        )
        group = by_name["device-1"]
        self.assertEqual(
            group.mapped["primary_ip4"],
            {"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}},
        )
        self.assertEqual(group.problems, ())
        self.assertEqual([i["name"] for i in group.mapped["interfaces"]], ["eth0", "eth1"])
        for iface in group.mapped["interfaces"]:
            self.assertNotIn("is_primary", iface)

    def test_each_device_has_its_own_primary(self) -> None:
        by_name = self._merge(
            [
                _prow("a", "eth0", "10.0.0.2/24", "true"),
                _prow("a", "eth1", "10.0.1.2/24", "false"),
                _prow("b", "eth0", "10.1.0.2/24", "false"),
                _prow("b", "eth1", "10.1.1.2/24", "true"),
            ]
        )
        self.assertEqual(by_name["a"].mapped["primary_ip4"]["address"], "10.0.0.2/24")
        self.assertEqual(by_name["b"].mapped["primary_ip4"]["address"], "10.1.1.2/24")

    def test_two_primaries_is_a_problem_and_sets_no_primary(self) -> None:
        group = self._merge(
            [
                _prow("a", "eth0", "10.0.0.2/24", "true"),
                _prow("a", "eth1", "10.0.1.2/24", "true"),
            ]
        )["a"]
        self.assertNotIn("primary_ip4", group.mapped)
        self.assertEqual([p.code for p in group.problems], ["multiple_primary_ip"])

    def test_no_primary_is_fine(self) -> None:
        group = self._merge([_prow("a", "eth0", "10.0.0.2/24", "false")])["a"]
        self.assertNotIn("primary_ip4", group.mapped)
        self.assertEqual(group.problems, ())

    def test_invalid_flag_value_is_a_problem(self) -> None:
        group = self._merge([_prow("a", "eth0", "10.0.0.2/24", "maybe")])["a"]
        self.assertEqual([p.code for p in group.problems], ["invalid_primary_flag"])

    def test_flag_on_row_without_ip_is_a_problem(self) -> None:
        group = self._merge([_prow("a", "eth0", "", "true")])["a"]
        self.assertEqual([p.code for p in group.problems], ["primary_without_address"])

    def test_single_row_mode(self) -> None:
        mapped, problems = map_single_row_with_problems(
            _prow("a", "eth0", "10.0.0.2/24", "yes", "black"), PRIMARY_RULES
        )
        self.assertEqual(mapped["primary_ip4"]["address"], "10.0.0.2/24")
        self.assertEqual(problems, ())

    def test_invalid_flag_never_installs_a_primary_address(self) -> None:
        group = self._merge(
            [
                _prow("a", "eth0", "10.0.0.2/24", "on"),
                _prow("a", "eth1", "10.0.1.2/24", "true"),
            ]
        )["a"]
        self.assertEqual([p.code for p in group.problems], ["invalid_primary_flag"])
        self.assertNotIn("primary_ip4", group.mapped)

    def test_invalid_flag_message_does_not_echo_the_cell(self) -> None:
        group = self._merge([_prow("a", "eth0", "10.0.0.2/24", "s3cr3t-community")])["a"]
        self.assertNotIn("s3cr3t", group.problems[0].message)

    def test_single_row_invalid_flag_sets_no_primary(self) -> None:
        mapped, problems = map_single_row_with_problems(
            _prow("a", "eth0", "10.0.0.2/24", "maybe"), PRIMARY_RULES
        )
        self.assertNotIn("primary_ip4", mapped)
        self.assertEqual([p.code for p in problems], ["invalid_primary_flag"])

    def test_single_row_without_primary_rule_unchanged(self) -> None:
        mapped = map_single_row(_row(**CORE), RULES)
        self.assertEqual(mapped["primary_ip4"], {"address": "192.168.178.240/24"})


if __name__ == "__main__":
    unittest.main()
