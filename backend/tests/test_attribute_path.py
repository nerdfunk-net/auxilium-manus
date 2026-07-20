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

    def test_resolves_scalar_leaf_from_parsed_namespace(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={"cisco_config": {"hostname": "router1", "platform": "IOS"}},
        )
        self.assertEqual(
            resolve_device_attribute(device, "parsed.cisco_config.hostname"),
            "router1",
        )

    def test_dict_or_list_leaf_from_parsed_namespace_is_none_via_scalar_resolver(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "cisco_config": {
                    "aaa_servers": {"servers": [{"name": "tacacs1", "address": "10.0.0.5"}]}
                }
            },
        )
        self.assertIsNone(
            resolve_device_attribute(device, "parsed.cisco_config.aaa_servers.servers")
        )

    def test_resolve_device_value_returns_raw_structure_from_parsed_namespace(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "cisco_config": {
                    "aaa_servers": {"servers": [{"name": "tacacs1", "address": "10.0.0.5"}]}
                }
            },
        )
        self.assertEqual(
            resolve_device_value(device, "parsed.cisco_config.aaa_servers.servers"),
            [{"name": "tacacs1", "address": "10.0.0.5"}],
        )

    def test_parsed_namespace_does_not_collide_with_attribute_bag_named_parsed(self) -> None:
        # attribute_bags never actually has a "parsed" key in practice, but the
        # reserved namespace must win over it rather than silently merging.
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"parsed": {"hostname": "from-bag"}},
            parsed={"cisco_config": {"hostname": "from-parsed-field"}},
        )
        self.assertEqual(
            resolve_device_attribute(device, "parsed.cisco_config.hostname"),
            "from-parsed-field",
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

    def test_present_when_parsed_server_list_is_non_empty(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "cisco_config": {
                    "aaa_servers": {"servers": [{"name": "tacacs1", "address": "10.0.0.5"}]}
                }
            },
        )
        state, value = resolve_device_attribute_state(
            device, "parsed.cisco_config.aaa_servers.servers"
        )
        self.assertEqual(state, AttributeState.PRESENT)
        self.assertIsNone(value)  # list contents aren't stringified — only PRESENT/EMPTY

    def test_empty_when_parsed_server_list_is_empty(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={"cisco_config": {"aaa_servers": {"servers": []}}},
        )
        state, value = resolve_device_attribute_state(
            device, "parsed.cisco_config.aaa_servers.servers"
        )
        self.assertEqual(state, AttributeState.EMPTY)
        self.assertIsNone(value)

    def test_absent_when_parsed_key_missing(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        state, value = resolve_device_attribute_state(device, "parsed.cisco_config.hostname")
        self.assertEqual(state, AttributeState.ABSENT)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
