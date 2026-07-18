"""Tests for attribute path resolution."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_path import (
    AttributeState,
    resolve_device_attribute,
    resolve_device_attribute_state,
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


class AttributeStateTests(unittest.TestCase):
    def test_absent_when_bag_missing(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        state, value = resolve_device_attribute_state(device, "tacacs.shared_secret")
        self.assertEqual(state, AttributeState.ABSENT)
        self.assertIsNone(value)

    def test_absent_when_key_missing_from_existing_bag(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {}},
        )
        state, value = resolve_device_attribute_state(device, "tacacs.shared_secret")
        self.assertEqual(state, AttributeState.ABSENT)
        self.assertIsNone(value)

    def test_null_when_key_explicitly_none(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": None}},
        )
        state, value = resolve_device_attribute_state(device, "tacacs.shared_secret")
        self.assertEqual(state, AttributeState.NULL)
        self.assertIsNone(value)

    def test_empty_when_key_is_empty_string(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": "  "}},
        )
        state, value = resolve_device_attribute_state(device, "tacacs.shared_secret")
        self.assertEqual(state, AttributeState.EMPTY)
        self.assertIsNone(value)

    def test_present_when_key_has_value(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": "s3cr3t"}},
        )
        state, value = resolve_device_attribute_state(device, "tacacs.shared_secret")
        self.assertEqual(state, AttributeState.PRESENT)
        self.assertEqual(value, "s3cr3t")

    def test_null_for_device_scalar_field(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab", platform=None)
        state, value = resolve_device_attribute_state(device, "device.platform")
        self.assertEqual(state, AttributeState.NULL)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
