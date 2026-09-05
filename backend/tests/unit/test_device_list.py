"""Tests for backend/workflow_steps/common/device_list.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.device_list import (
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
                DeviceEntry(name="router1", ip_address=None),
                DeviceEntry(name="switch2", ip_address=None),
            ],
        )

    def test_bare_ip_line_is_detected_as_ip_address(self) -> None:
        entries = parse_device_list_text("10.0.0.5")
        self.assertEqual(entries, [DeviceEntry(name=None, ip_address="10.0.0.5")])

    def test_name_comma_ip_line_sets_both_fields(self) -> None:
        entries = parse_device_list_text("router1.example.com,10.0.0.6")
        self.assertEqual(
            entries, [DeviceEntry(name="router1.example.com", ip_address="10.0.0.6")]
        )

    def test_invalid_ip_after_comma_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_device_list_text("router1,not-an-ip")

    def test_deduplicates_case_insensitively(self) -> None:
        entries = parse_device_list_text("Router1\nrouter1\nROUTER1")
        self.assertEqual(entries, [DeviceEntry(name="Router1", ip_address=None)])

    def test_none_input_yields_no_entries(self) -> None:
        self.assertEqual(parse_device_list_text(None), [])

    def test_non_string_input_is_coerced_to_string(self) -> None:
        # A non-str run-input value (e.g. accidentally stored as a number)
        # should not raise — it's coerced to text and parsed as one line.
        entries = parse_device_list_text(12345)
        self.assertEqual(entries, [DeviceEntry(name="12345", ip_address=None)])


class NormalizeDeviceEntriesTests(unittest.TestCase):
    def test_accepts_bare_strings_and_dicts(self) -> None:
        entries = normalize_device_entries(["router1", {"ip_address": "10.0.0.5"}])
        self.assertEqual(
            entries,
            [
                DeviceEntry(name="router1", ip_address=None),
                DeviceEntry(name=None, ip_address="10.0.0.5"),
            ],
        )

    def test_non_list_input_yields_no_entries(self) -> None:
        self.assertEqual(normalize_device_entries("not-a-list"), [])

    def test_invalid_ip_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_device_entries([{"name": "router1", "ip_address": "bad"}])


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
