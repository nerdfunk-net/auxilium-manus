"""Tests for attribute write helpers."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext
from services.workflow_context.attribute_path import resolve_device_attribute
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


class AttributeWriteIsolationTests(unittest.TestCase):
    """A write must never change the input device or any device sharing its dicts."""

    def _device(self, device_id: str, bags: dict) -> DeviceContext:
        return DeviceContext(
            id=device_id, name=device_id, hostname=device_id, attribute_bags=bags
        )

    def test_deep_write_does_not_mutate_the_input_device(self) -> None:
        device = self._device("d1", {"nautobot": {"location": {"name": "A"}}})
        updated = set_device_attribute(device, "nautobot.location.name", "B")
        self.assertEqual(device.attribute_bags["nautobot"]["location"], {"name": "A"})
        self.assertEqual(updated.attribute_bags["nautobot"]["location"], {"name": "B"})

    def test_deep_write_does_not_leak_into_a_device_sharing_the_nested_dict(self) -> None:
        shared = {"site": {"vlan": {"mgmt": 10}}}
        d1 = self._device("d1", {"inv": shared})
        d2 = self._device("d2", {"inv": shared})
        updated = set_device_attribute(d1, "inv.site.vlan.mgmt", 99)
        self.assertEqual(updated.attribute_bags["inv"]["site"]["vlan"]["mgmt"], 99)
        self.assertEqual(d2.attribute_bags["inv"]["site"]["vlan"]["mgmt"], 10)
        self.assertEqual(shared["site"]["vlan"]["mgmt"], 10)

if __name__ == "__main__":
    unittest.main()
