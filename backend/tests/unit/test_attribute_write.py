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

class ListItemWriteTests(unittest.TestCase):
    """``bag.list[field=value].leaf`` finds or appends a list item."""

    @staticmethod
    def _device(bags: dict) -> DeviceContext:
        return DeviceContext(id="d", name="d", hostname="d", attribute_bags=bags)

    def test_updates_existing_item(self) -> None:
        shared = [{"name": "Ethernet0/0", "mtu": 1500}, {"name": "Ethernet0/1"}]
        device = self._device({"nautobot": {"interfaces": shared}})
        updated = set_device_attribute(
            device, "nautobot.interfaces[name=Ethernet0/0].mac_address", "AA:BB:CC:00:01:00"
        )
        items = updated.attribute_bags["nautobot"]["interfaces"]
        self.assertEqual(
            items[0], {"name": "Ethernet0/0", "mtu": 1500, "mac_address": "AA:BB:CC:00:01:00"}
        )
        self.assertEqual(items[1], {"name": "Ethernet0/1"})
        # the original (possibly shared) list and its dicts are untouched
        self.assertEqual(shared[0], {"name": "Ethernet0/0", "mtu": 1500})

    def test_appends_missing_item(self) -> None:
        device = self._device({"nautobot": {"interfaces": [{"name": "Ethernet0/1"}]}})
        updated = set_device_attribute(device, "nautobot.interfaces[name=Loopback0].mtu", "1514")
        self.assertEqual(
            updated.attribute_bags["nautobot"]["interfaces"],
            [{"name": "Ethernet0/1"}, {"name": "Loopback0", "mtu": "1514"}],
        )

    def test_creates_list_when_absent(self) -> None:
        updated = set_device_attribute(
            self._device({}), "nautobot.interfaces[name=Gi0/0].duplex", "full"
        )
        self.assertEqual(
            updated.attribute_bags["nautobot"]["interfaces"],
            [{"name": "Gi0/0", "duplex": "full"}],
        )

    def test_name_with_dot_is_not_split(self) -> None:
        updated = set_device_attribute(
            self._device({}), "nautobot.interfaces[name=Gi0/0.100].mtu", "1500"
        )
        self.assertEqual(
            updated.attribute_bags["nautobot"]["interfaces"][0],
            {"name": "Gi0/0.100", "mtu": "1500"},
        )
        self.assertEqual(
            resolve_device_attribute(updated, "nautobot.interfaces[name=Gi0/0.100].mtu"), "1500"
        )

    def test_repeated_writes_reuse_the_same_item(self) -> None:
        device = self._device({})
        device = set_device_attribute(device, "nautobot.interfaces[name=Gi0/0].mtu", "1500")
        device = set_device_attribute(device, "nautobot.interfaces[name=Gi0/0].speed", "1000")
        self.assertEqual(
            device.attribute_bags["nautobot"]["interfaces"],
            [{"name": "Gi0/0", "mtu": "1500", "speed": "1000"}],
        )

    def test_rejects_non_list_target(self) -> None:
        device = self._device({"nautobot": {"interfaces": {"a": 1}}})
        with self.assertRaises(ValueError):
            set_device_attribute(device, "nautobot.interfaces[name=x].mtu", "1")

    def test_rejects_selectors_the_writer_cannot_honour(self) -> None:
        # The reader accepts a dotted filter field and a literal [index]; a write that cannot
        # land where the reader looks must fail loudly, not succeed in the wrong place.
        for path in (
            "nautobot.interfaces[lag.name=Po1].mtu",
            "nautobot.interfaces[0].mtu",
            "nautobot.interfaces[12].mtu",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                set_device_attribute(
                    self._device({"nautobot": {"interfaces": [{"name": "a"}]}}), path, "1"
                )

    def test_rejects_empty_filter_value_and_selector_without_leaf(self) -> None:
        with self.assertRaises(ValueError):
            set_device_attribute(self._device({}), "nautobot.interfaces[name=].mtu", "1")
        with self.assertRaises(ValueError):
            set_device_attribute(self._device({}), "nautobot.interfaces[name=x]", "1")


if __name__ == "__main__":
    unittest.main()
