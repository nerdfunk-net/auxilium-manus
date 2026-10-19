"""Tests for backend/workflow_steps/common/device_list.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.device_list import (
    DEFAULT_NETWORK_DRIVER,
    DeviceEntry,
    device_context_from_entry,
    normalize_device_entries,
    parse_device_list_text,
)


class ParseDeviceListTextTests(unittest.TestCase):
    def test_splits_on_newlines_and_ignores_blank_lines(self) -> None:
        entries = parse_device_list_text("router1\n\n  \nswitch2\n")
        self.assertEqual(
            entries,
            [
                DeviceEntry(name="router1", ip_address=None, network_driver="cisco_ios"),
                DeviceEntry(name="switch2", ip_address=None, network_driver="cisco_ios"),
            ],
        )

    def test_bare_ip_line_is_detected_as_ip_address(self) -> None:
        entries = parse_device_list_text("10.0.0.5")
        self.assertEqual(
            entries, [DeviceEntry(name=None, ip_address="10.0.0.5", network_driver="cisco_ios")]
        )

    def test_name_comma_ip_line_sets_both_fields(self) -> None:
        entries = parse_device_list_text("router1.example.com,10.0.0.6")
        self.assertEqual(
            entries,
            [
                DeviceEntry(
                    name="router1.example.com", ip_address="10.0.0.6", network_driver="cisco_ios"
                )
            ],
        )

    def test_invalid_ip_after_comma_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_device_list_text("router1,not-an-ip")

    def test_deduplicates_case_insensitively(self) -> None:
        entries = parse_device_list_text("Router1\nrouter1\nROUTER1")
        self.assertEqual(
            entries, [DeviceEntry(name="Router1", ip_address=None, network_driver="cisco_ios")]
        )

    def test_none_input_yields_no_entries(self) -> None:
        self.assertEqual(parse_device_list_text(None), [])

    def test_non_string_input_is_coerced_to_string(self) -> None:
        # A non-str run-input value (e.g. accidentally stored as a number)
        # should not raise — it's coerced to text and parsed as one line.
        entries = parse_device_list_text(12345)
        self.assertEqual(
            entries, [DeviceEntry(name="12345", ip_address=None, network_driver="cisco_ios")]
        )


class NetworkDriverParsingTests(unittest.TestCase):
    def test_three_field_line_sets_the_driver(self) -> None:
        entries = parse_device_list_text("r1,10.0.0.1,junos")
        self.assertEqual(
            entries, [DeviceEntry(name="r1", ip_address="10.0.0.1", network_driver="juniper_junos")]
        )

    def test_empty_middle_field_leaves_the_ip_unset(self) -> None:
        entries = parse_device_list_text("r1,,cisco_nxos")
        self.assertEqual(
            entries, [DeviceEntry(name="r1", ip_address=None, network_driver="cisco_nxos")]
        )

    def test_missing_driver_gets_the_default_before_dedup(self) -> None:
        entries = parse_device_list_text("r1,10.0.0.1")
        self.assertEqual(entries[0].network_driver, "cisco_ios")
        self.assertEqual(
            parse_device_list_text("r1,10.0.0.1", default_driver="cisco_nxos")[0].network_driver,
            "cisco_nxos",
        )

    def test_alias_is_canonicalized(self) -> None:
        self.assertEqual(parse_device_list_text("r1,10.0.0.1,ios")[0].network_driver, "cisco_ios")
        self.assertEqual(parse_device_list_text("r1,10.0.0.1,IOS-XE")[0].network_driver, "cisco_xe")

    def test_implicit_default_and_explicit_driver_are_one_device(self) -> None:
        for text in (
            "r1,10.0.0.1\nr1,10.0.0.1,cisco_ios",
            "r1,10.0.0.1,ios\nr1,10.0.0.1,cisco_ios",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(parse_device_list_text(text)), 1)

    def test_unknown_driver_names_the_line(self) -> None:
        with self.assertRaisesRegex(ValueError, r"network driver 'nope'.*line 2"):
            parse_device_list_text("r1\nr2,10.0.0.1,nope")

    def test_extra_fields_raise(self) -> None:
        with self.assertRaises(ValueError):
            parse_device_list_text("r1,10.0.0.1,junos,extra")

    def test_same_device_with_different_drivers_is_kept_apart(self) -> None:
        entries = parse_device_list_text("r1,10.0.0.1,junos\nr1,10.0.0.1,cisco_ios")
        self.assertEqual(len(entries), 2)


class NormalizeDeviceEntriesTests(unittest.TestCase):
    def test_accepts_bare_strings_and_dicts(self) -> None:
        entries = normalize_device_entries(["router1", {"ip_address": "10.0.0.5"}])
        self.assertEqual(
            entries,
            [
                DeviceEntry(name="router1", ip_address=None, network_driver="cisco_ios"),
                DeviceEntry(name=None, ip_address="10.0.0.5", network_driver="cisco_ios"),
            ],
        )

    def test_non_list_input_yields_no_entries(self) -> None:
        self.assertEqual(normalize_device_entries("not-a-list"), [])

    def test_invalid_ip_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_device_entries([{"name": "router1", "ip_address": "bad"}])

    def test_dict_driver_is_read_and_validated(self) -> None:
        entries = normalize_device_entries(
            [{"name": "r1", "ip_address": "10.0.0.1", "network_driver": "junos"}]
        )
        self.assertEqual(entries[0].network_driver, "juniper_junos")
        with self.assertRaisesRegex(ValueError, "network driver 'nope'"):
            normalize_device_entries([{"name": "r1", "network_driver": "nope"}])

    def test_blank_driver_gets_the_default(self) -> None:
        entries = normalize_device_entries([{"name": "r1", "network_driver": "  "}])
        self.assertEqual(entries[0].network_driver, "cisco_ios")

    def test_alias_and_default_rows_are_one_device(self) -> None:
        entries = normalize_device_entries(
            [
                {"name": "r1", "ip_address": "10.0.0.1"},
                {"name": "r1", "ip_address": "10.0.0.1", "network_driver": "ios"},
            ]
        )
        self.assertEqual(len(entries), 1)


class DeviceContextFromEntryTests(unittest.TestCase):
    def test_default_source_and_bag_name_is_list(self) -> None:
        device = device_context_from_entry(
            DeviceEntry(name="router1", ip_address=None), index=0, node_id="node-1"
        )
        self.assertEqual(device.source, "list")
        self.assertIn("list", device.attribute_bags)
        self.assertTrue(device.id.startswith("list-"))

    def test_custom_source_and_bag_name_stay_independent(self) -> None:
        device = device_context_from_entry(
            DeviceEntry(name="router1", ip_address=None),
            index=0,
            node_id="node-1",
            source="run_input",
            attribute_bag_name="get_from_user",
        )
        self.assertEqual(device.source, "run_input")
        self.assertTrue(device.id.startswith("run_input-"))
        self.assertIn("get_from_user", device.attribute_bags)
        # The reserved "run_input" bag key must never be pre-populated, even
        # though DeviceContext.source is "run_input" — see the reserved-name
        # guard in seed_run_input_bag / attribute_write.py.
        self.assertNotIn("run_input", device.attribute_bags)

    def test_driver_defaults_to_cisco_ios(self) -> None:
        device = device_context_from_entry(
            DeviceEntry(name="router1", ip_address=None), index=0, node_id="node-1"
        )
        self.assertEqual(DEFAULT_NETWORK_DRIVER, "cisco_ios")
        self.assertEqual(device.network_driver, "cisco_ios")

    def test_entry_driver_wins_over_the_default(self) -> None:
        device = device_context_from_entry(
            DeviceEntry(name="r1", ip_address=None, network_driver="junos"),
            index=0,
            node_id="node-1",
            default_driver="cisco_nxos",
        )
        self.assertEqual(device.network_driver, "junos")
        self.assertEqual(device.attribute_bags["list"]["network_driver"], "junos")

    def test_caller_default_applies_when_entry_has_none(self) -> None:
        device = device_context_from_entry(
            DeviceEntry(name="r1", ip_address=None),
            index=0,
            node_id="node-1",
            default_driver="cisco_nxos",
        )
        self.assertEqual(device.network_driver, "cisco_nxos")

    def test_reserved_attribute_bag_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            device_context_from_entry(
                DeviceEntry(name="router1", ip_address=None),
                index=0,
                node_id="node-1",
                source="run_input",
                attribute_bag_name="run_input",
            )


if __name__ == "__main__":
    unittest.main()
