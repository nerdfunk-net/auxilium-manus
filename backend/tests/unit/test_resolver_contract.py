"""One table, three resolvers: scalars read the same through attribute paths and templates."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.attribute_path import (
    resolve_device_attribute,
    resolve_device_value,
)
from services.workflow_context.device_template import render_device_template
from workflow_steps.route_on_attribute.executor import execute


def _device() -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="sw1",
        hostname="sw1.example.com",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        attribute_bags={
            "single": {"only": "v"},
            "double": {"a": "1", "b": "2"},
            "nautobot": {"custom_fields": {"x": "cf"}, "role": {"name": "edge"}},
        },
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class ResolverContractTests(unittest.TestCase):
    def test_scalar_rows_agree_across_resolvers(self) -> None:
        device = _device()
        rows = {
            "device.primary_ip4": "10.0.0.1",
            "device.primary_ip4_cidr": "10.0.0.1/24",
            "device.hostname": "sw1.example.com",
            "device.name": "sw1",
            "nautobot.custom_fields.x": "cf",
            "nautobot.role.name": "edge",
        }
        for path, expected in rows.items():
            with self.subTest(path=path):
                self.assertEqual(resolve_device_attribute(device, path), expected)
                self.assertEqual(resolve_device_value(device, path), expected)
                self.assertEqual(render_device_template("{" + path + "}", device), expected)

    def test_single_key_bag_resolves_by_bare_name_two_key_bag_does_not(self) -> None:
        device = _device()
        self.assertEqual(resolve_device_attribute(device, "single"), "v")
        self.assertIsNone(resolve_device_attribute(device, "double"))

    def test_unknown_device_field_is_none(self) -> None:
        self.assertIsNone(resolve_device_attribute(_device(), "device.custom.x"))


class RouteOnBareIpTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_on_attribute_matches_bare_ip(self) -> None:
        context = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()})
        outcomes = await execute(
            config={
                "attribute_path": "device.primary_ip4",
                "routes": [{"outcome": "lab", "values": ["10.0.0.1"]}],
            },
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertIn("d1", by_name["lab"].context.devices)


if __name__ == "__main__":
    unittest.main()
