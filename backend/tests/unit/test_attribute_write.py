"""Tests for attribute write helpers."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.common.attribute_write import set_device_attribute


class AttributeWriteTests(unittest.TestCase):
    def test_sets_nested_bag_value(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
        )
        updated = set_device_attribute(device, "nautobot.location.name", "office-a")
        self.assertEqual(
            resolve_device_attribute(updated, "nautobot.location.name"),
            "office-a",
        )
        self.assertEqual(
            resolve_device_attribute(updated, "nautobot.role.name"),
            "access-switch",
        )
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

    def test_overwrites_existing_custom_attribute(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"custom": {"location": "old"}},
        )
        updated = set_device_attribute(device, "custom.location", "new")
        self.assertEqual(resolve_device_attribute(updated, "custom.location"), "new")

    def test_sets_device_scalar_with_prefix(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        updated = set_device_attribute(device, "device.platform", "cisco-ios")
        self.assertEqual(updated.platform, "cisco-ios")

    def test_rejects_write_to_reserved_parsed_namespace(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        with self.assertRaises(ValueError):
            set_device_attribute(device, "parsed.cisco_config", "anything")


if __name__ == "__main__":
    unittest.main()
