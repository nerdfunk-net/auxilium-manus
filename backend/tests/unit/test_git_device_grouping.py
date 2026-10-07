"""Tests for services/git/device_grouping.py (CSV simple + multi-line merge)."""

from __future__ import annotations

import copy
import unittest

from services.git.device_grouping import map_single_row, merge_device_rows
from services.git.device_mapping import MappingRule

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


if __name__ == "__main__":
    unittest.main()
