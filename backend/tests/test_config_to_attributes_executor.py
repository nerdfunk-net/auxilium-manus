"""Tests for the config-to-attributes executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.config_to_attributes.config import get_config
from workflow_steps.config_to_attributes.executor import execute

_BASE_CONFIG = {**get_config()}


def _l3_interfaces(*items: dict) -> dict:
    return {"l3_interfaces": list(items)}


def _device(
    device_id: str, *, parsed: dict | None = None, nautobot_bag: dict | None = None
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        source="list",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        parsed=parsed or {},
        attribute_bags={"nautobot": nautobot_bag} if nautobot_bag is not None else {},
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


class ConfigToAttributesExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_type_mapping_and_status(self) -> None:
        device = _device(
            "dev-1",
            parsed={
                "cisco_config": _l3_interfaces(
                    {"name": "GigabitEthernet0/1", "children": []},
                    {"name": "Ethernet0/0", "children": []},
                    {"name": "Loopback0", "children": []},
                )
            },
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertEqual(by_name["GigabitEthernet0/1"]["type"], "1000base-t")
        self.assertEqual(by_name["Ethernet0/0"]["type"], "100base-tx")
        self.assertEqual(by_name["Loopback0"]["type"], "virtual")
        for iface in interfaces:
            self.assertEqual(iface["status"], "Active")

    async def test_enabled_false_when_shutdown_in_children(self) -> None:
        device = _device(
            "dev-1",
            parsed={
                "cisco_config": _l3_interfaces(
                    {"name": "Ethernet0/2", "children": ["description test", "shutdown"]},
                    {"name": "Ethernet0/3", "children": ["description test"]},
                )
            },
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertFalse(by_name["Ethernet0/2"]["enabled"])
        self.assertTrue(by_name["Ethernet0/3"]["enabled"])

    async def test_primary_and_secondary_ip(self) -> None:
        device = _device(
            "dev-1",
            parsed={
                "cisco_config": _l3_interfaces(
                    {
                        "name": "Ethernet0/0",
                        "description": "xxx",
                        "ip_address": "192.168.178.120",
                        "mask": "255.255.255.0",
                        "sec_ip_address": "192.168.178.120",
                        "sec_mask": "255.255.255.0",
                        "sec_subnet": "192.168.178.0/24",
                        "children": [],
                    },
                    {
                        # partial secondary fields -> no secondary IP
                        "name": "Ethernet0/1",
                        "ip_address": "192.168.179.240",
                        "mask": "255.255.255.0",
                        "sec_ip_address": "10.0.0.1",
                        "sec_mask": None,
                        "sec_subnet": None,
                        "children": [],
                    },
                    {
                        # no ip at all
                        "name": "Ethernet0/2",
                        "children": [],
                    },
                )
            },
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        self.assertEqual(by_name["Ethernet0/0"]["description"], "xxx")
        self.assertEqual(
            by_name["Ethernet0/0"]["ip_addresses"],
            [
                {"address": "192.168.178.120/24", "namespace": "Global"},
                {"address": "192.168.178.120/24", "namespace": "Global"},
            ],
        )
        self.assertEqual(
            by_name["Ethernet0/1"]["ip_addresses"],
            [{"address": "192.168.179.240/24", "namespace": "Global"}],
        )
        self.assertNotIn("ip_addresses", by_name["Ethernet0/2"])
        self.assertNotIn("description", by_name["Ethernet0/2"])

    async def test_config_source_both_nested_selection(self) -> None:
        device = _device(
            "dev-1",
            parsed={
                "cisco_config": {
                    "running": _l3_interfaces({"name": "Ethernet0/0", "children": []}),
                    "startup": _l3_interfaces({"name": "Ethernet0/1", "children": []}),
                }
            },
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "config_source": "startup"},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual([i["name"] for i in interfaces], ["Ethernet0/1"])

    async def test_config_source_single_inlined_fallback(self) -> None:
        # upstream Parse Cisco Config ran with config_source: running (not "both") ->
        # model is inlined directly, no running/startup sub-keys.
        device = _device(
            "dev-1",
            parsed={"cisco_config": _l3_interfaces({"name": "Ethernet0/0", "children": []})},
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "config_source": "startup"},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual([i["name"] for i in interfaces], ["Ethernet0/0"])

    async def test_merge_preserves_other_bag_keys_and_replaces_same_named_interface(self) -> None:
        device = _device(
            "dev-1",
            parsed={"cisco_config": _l3_interfaces({"name": "Ethernet0/0", "children": []})},
            nautobot_bag={
                "role": {"name": "Network"},
                "interfaces": [{"name": "Ethernet0/0", "type": "other", "status": "Deprecated"}],
            },
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["role"], {"name": "Network"})
        self.assertEqual(len(bag["interfaces"]), 1)
        self.assertEqual(bag["interfaces"][0]["status"], "Active")
        self.assertEqual(bag["interfaces"][0]["type"], "100base-tx")

    async def test_noop_when_layer3_interfaces_not_selected(self) -> None:
        device = _device(
            "dev-1",
            parsed={"cisco_config": _l3_interfaces({"name": "Ethernet0/0", "children": []})},
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "attributes": []},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        self.assertNotIn("nautobot", outcomes[0].context.devices["dev-1"].attribute_bags)

    async def test_raises_when_no_device_has_parsed_data(self) -> None:
        device = _device("dev-1", parsed={})
        with self.assertRaises(ValueError):
            await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_defaults_apply_when_config_is_empty(self) -> None:
        # A node dropped on the canvas without ever opening its config panel
        # saves an empty (or partial) pluginConfig — defaults must still apply,
        # matching parse-cisco-config's own output_key/config_source fallback.
        device = _device(
            "dev-1",
            parsed={"cisco_config": _l3_interfaces({"name": "Ethernet0/0", "children": []})},
        )
        outcomes = await execute(
            config={},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual([i["name"] for i in interfaces], ["Ethernet0/0"])

    async def test_capability_attributes_set(self) -> None:
        device = _device(
            "dev-1",
            parsed={"cisco_config": _l3_interfaces({"name": "Ethernet0/0", "children": []})},
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
        )
        self.assertIn(Capability.ATTRIBUTES, outcomes[0].context.devices["dev-1"].capabilities)


if __name__ == "__main__":
    unittest.main()
