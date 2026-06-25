"""Tests for attribute path resolution."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_path import (
    resolve_device_attribute,
    resolve_device_value,
)


class AttributePathTests(unittest.TestCase):
    def test_resolves_device_scalar_shorthand(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
        )
        self.assertEqual(resolve_device_attribute(device, "network_driver"), "cisco_ios")

    def test_resolves_device_scalar_with_prefix(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            platform="cisco-ios",
        )
        self.assertEqual(resolve_device_attribute(device, "device.platform"), "cisco-ios")

    def test_resolves_namespaced_attribute_bag(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={
                "nautobot": {
                    "role": {"name": "access-switch"},
                    "location": {"name": "office-a"},
                }
            },
        )
        self.assertEqual(
            resolve_device_attribute(device, "nautobot.role.name"),
            "access-switch",
        )
        self.assertEqual(
            resolve_device_attribute(device, "nautobot.location.name"),
            "office-a",
        )

    def test_resolves_custom_user_bag(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"custom": {"backup_tier": "gold"}},
        )
        self.assertEqual(
            resolve_device_attribute(device, "custom.backup_tier"),
            "gold",
        )

    def test_returns_none_for_missing_path(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        self.assertIsNone(resolve_device_attribute(device, "nautobot.role.name"))

    def test_resolve_device_value_returns_structured_data(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"role": {"name": "access-switch", "id": "abc"}}},
        )
        self.assertEqual(
            resolve_device_value(device, "nautobot.role"),
            {"name": "access-switch", "id": "abc"},
        )


if __name__ == "__main__":
    unittest.main()
