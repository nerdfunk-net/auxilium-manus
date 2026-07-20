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


_ACCESS_LISTS = [
    {
        "name": "MGMT_100",
        "style": "named",
        "type": "standard",
        "entries": [
            {
                "action": "permit",
                "source": "172.16.9.100",
                "destination": None,
                "sequence": "10",
            }
        ],
    },
    {
        "name": "TRAFFIC_in",
        "style": "named",
        "type": "extended",
        "entries": [
            {
                "action": "permit",
                "source": "192.168.178.240",
                "destination": "192.168.0.2",
                "sequence": "110",
            }
        ],
    },
]


class FilterSegmentTests(unittest.TestCase):
    """Tests for the "key[field=value]" path segment — filters a list to the
    item matching field==value before continuing traversal, e.g.
    parsed.cisco_config.access_lists[name=MGMT_100].entries."""

    def _device(self) -> DeviceContext:
        return DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={"cisco_config": {"access_lists": _ACCESS_LISTS}},
        )

    def test_resolve_device_value_reaches_nested_list_after_filter(self) -> None:
        device = self._device()
        entries = resolve_device_value(
            device, "parsed.cisco_config.access_lists[name=MGMT_100].entries"
        )
        self.assertEqual(entries, _ACCESS_LISTS[0]["entries"])

    def test_resolve_device_value_reaches_scalar_field_after_filter(self) -> None:
        device = self._device()
        self.assertEqual(
            resolve_device_value(
                device, "parsed.cisco_config.access_lists[name=TRAFFIC_in].type"
            ),
            "extended",
        )

    def test_resolve_device_attribute_reaches_scalar_leaf_after_filter(self) -> None:
        device = self._device()
        self.assertEqual(
            resolve_device_attribute(
                device, "parsed.cisco_config.access_lists[name=MGMT_100].style"
            ),
            "named",
        )

    def test_state_absent_when_filter_matches_nothing(self) -> None:
        device = self._device()
        state, value = resolve_device_attribute_state(
            device, "parsed.cisco_config.access_lists[name=DOES_NOT_EXIST].entries"
        )
        self.assertEqual(state, AttributeState.ABSENT)
        self.assertIsNone(value)

    def test_state_present_when_filter_matches(self) -> None:
        device = self._device()
        state, _ = resolve_device_attribute_state(
            device, "parsed.cisco_config.access_lists[name=MGMT_100].entries"
        )
        self.assertEqual(state, AttributeState.PRESENT)

    def test_filter_value_containing_dots_is_not_split(self) -> None:
        # Regression: a filter value like an IP address must not be split by
        # the "." tokenizer just because it contains dots.
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "cisco_config": {
                    "l3_interfaces": [
                        {"name": "Ethernet0/0", "ip_address": "192.168.178.120"},
                        {"name": "Ethernet0/1", "ip_address": "192.168.179.240"},
                    ]
                }
            },
        )
        self.assertEqual(
            resolve_device_value(
                device,
                "parsed.cisco_config.l3_interfaces[ip_address=192.168.179.240].name",
            ),
            "Ethernet0/1",
        )

    def test_filter_on_non_list_value_returns_none(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={"cisco_config": {"hostname": "router1"}},
        )
        self.assertIsNone(
            resolve_device_value(device, "parsed.cisco_config.hostname[name=x].y")
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
