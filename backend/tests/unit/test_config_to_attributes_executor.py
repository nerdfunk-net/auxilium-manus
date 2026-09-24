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


def _parsed_model(
    *,
    l3_interfaces: list[dict] | None = None,
    l2_access_interfaces: list[dict] | None = None,
    l2_trunk_interfaces: list[dict] | None = None,
    port_channels: list[dict] | None = None,
) -> dict:
    return {
        "l3_interfaces": l3_interfaces or [],
        "l2_access_interfaces": l2_access_interfaces or [],
        "l2_trunk_interfaces": l2_trunk_interfaces or [],
        "port_channels": port_channels or [],
    }


def _parsed(*items: dict, source: str = "running") -> dict:
    """A parse-cisco-config entry — always ``{"running": ..., "startup": ...}``,
    with the branch other than ``source`` left ``None``."""
    model = _l3_interfaces(*items)
    return {
        "cisco_config": {
            "running": model if source == "running" else None,
            "startup": model if source == "startup" else None,
        }
    }


def _parsed_full(model: dict, *, source: str = "running") -> dict:
    """Like ``_parsed`` but takes a full parsed-model dict (see ``_parsed_model``)."""
    return {
        "cisco_config": {
            "running": model if source == "running" else None,
            "startup": model if source == "startup" else None,
        }
    }


def _device(
    device_id: str,
    *,
    parsed: dict | None = None,
    nautobot_bag: dict | None = None,
    primary_ip4: str | None = None,
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
        primary_ip4=primary_ip4,
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
            parsed=_parsed(
                {"name": "GigabitEthernet0/1", "children": []},
                {"name": "Ethernet0/0", "children": []},
                {"name": "Loopback0", "children": []},
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
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
            parsed=_parsed(
                {"name": "Ethernet0/2", "children": ["description test", "shutdown"]},
                {"name": "Ethernet0/3", "children": ["description test"]},
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertFalse(by_name["Ethernet0/2"]["enabled"])
        self.assertTrue(by_name["Ethernet0/3"]["enabled"])

    async def test_primary_and_secondary_ip(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
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
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        self.assertEqual(by_name["Ethernet0/0"]["description"], "xxx")
        self.assertEqual(
            by_name["Ethernet0/0"]["ip_addresses"],
            [
                {
                    "address": "192.168.178.120/24",
                    "namespace": "Global",
                },
                {
                    "address": "192.168.178.120/24",
                    "namespace": "Global",
                    "ip_role": "secondary",
                },
            ],
        )
        self.assertEqual(
            by_name["Ethernet0/1"]["ip_addresses"],
            [
                {
                    "address": "192.168.179.240/24",
                    "namespace": "Global",
                }
            ],
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
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual([i["name"] for i in interfaces], ["Ethernet0/1"])

    async def test_config_source_selects_none_branch_when_not_parsed(self) -> None:
        # Upstream parsed running only; this step asks for startup -> the
        # startup branch is None, so the device is skipped (no interfaces).
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}, source="running"),
        )
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "config_source": "startup"},
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_merge_preserves_other_bag_keys_and_replaces_same_named_interface(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}),
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
            device_sessions=MagicMock(),
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["role"], {"name": "Network"})
        self.assertEqual(len(bag["interfaces"]), 1)
        self.assertEqual(bag["interfaces"][0]["status"], "Active")
        self.assertEqual(bag["interfaces"][0]["type"], "100base-tx")

    async def test_noop_when_interfaces_not_selected(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}),
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "attributes": []},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertNotIn("nautobot", outcomes[0].context.devices["dev-1"].attribute_bags)

    async def test_noop_when_old_layer3_interfaces_key_used(self) -> None:
        # Renamed layer3_interfaces -> interfaces; the old key is no longer
        # recognized and must silently no-op rather than build anything.
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}),
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "attributes": ["layer3_interfaces"]},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
            )

    async def test_defaults_apply_when_config_is_empty(self) -> None:
        # A node dropped on the canvas without ever opening its config panel
        # saves an empty (or partial) pluginConfig — defaults must still apply,
        # matching parse-cisco-config's own output_key/config_source fallback.
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}),
        )
        outcomes = await execute(
            config={},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual([i["name"] for i in interfaces], ["Ethernet0/0"])

    async def test_genie_source_format_builds_interfaces(self) -> None:
        # Trimmed from a real get-pyats-running-config output for "show running-config".
        running_config = {
            "hostname LAB": {},
            "interface Loopback0": {
                "description Loopback": {},
                "ip address 192.168.179.254 255.255.255.255": {},
            },
            "interface Ethernet0/0": {
                "description xxx": {},
                "ip address 192.168.178.120 255.255.255.0 secondary": {},
                "ip address 192.168.178.240 255.255.255.0": {},
            },
            "interface Ethernet0/2": {
                "description test": {},
                "no ip address": {},
                "shutdown": {},
            },
            "interface Ethernet0/1": {
                "switchport access vlan 100": {},
                "switchport mode access": {},
            },
            "interface Ethernet0/3": {
                "channel-group 10 mode active": {},
            },
            "router ospf 100": {"network 192.168.178.240 0.0.0.0 area 0": {}},
        }
        device = _device(
            "dev-1",
            parsed={"cisco_config": {"running": running_config}},
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "source_format": "genie"},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        self.assertEqual(
            set(by_name),
            {"Loopback0", "Ethernet0/0", "Ethernet0/2", "Ethernet0/1", "Ethernet0/3"},
        )

        eth01 = by_name["Ethernet0/1"]
        self.assertEqual(eth01["mode"], "access")
        self.assertEqual(eth01["untagged_vlan"], 100)

        eth03 = by_name["Ethernet0/3"]
        self.assertEqual(eth03["lag"], "Port-channel10")

        self.assertEqual(by_name["Loopback0"]["type"], "virtual")
        self.assertEqual(by_name["Loopback0"]["description"], "Loopback")
        self.assertEqual(
            by_name["Loopback0"]["ip_addresses"],
            [{"address": "192.168.179.254/32", "namespace": "Global"}],
        )

        eth00 = by_name["Ethernet0/0"]
        self.assertEqual(eth00["description"], "xxx")
        self.assertTrue(eth00["enabled"])
        self.assertEqual(
            eth00["ip_addresses"],
            [
                {
                    "address": "192.168.178.120/24",
                    "namespace": "Global",
                    "ip_role": "secondary",
                },
                {
                    "address": "192.168.178.240/24",
                    "namespace": "Global",
                },
            ],
        )

        eth02 = by_name["Ethernet0/2"]
        self.assertFalse(eth02["enabled"])
        self.assertNotIn("ip_addresses", eth02)

    async def test_genie_channel_group_without_mode_suffix_sets_lag(self) -> None:
        running_config = {
            "interface Ethernet0/4": {"channel-group 5": {}},
        }
        device = _device("dev-1", parsed={"cisco_config": {"running": running_config}})
        outcomes = await execute(
            config={**_BASE_CONFIG, "source_format": "genie"},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual(interfaces[0]["lag"], "Port-channel5")

    async def test_genie_access_vlan_without_explicit_switchport_mode_line(self) -> None:
        running_config = {
            "interface Ethernet0/5": {"switchport access vlan 200": {}},
        }
        device = _device("dev-1", parsed={"cisco_config": {"running": running_config}})
        outcomes = await execute(
            config={**_BASE_CONFIG, "source_format": "genie"},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertEqual(interfaces[0]["mode"], "access")
        self.assertEqual(interfaces[0]["untagged_vlan"], 200)

    async def test_genie_source_format_rejects_startup_config_source(self) -> None:
        device = _device("dev-1", parsed={"cisco_config": {"running": {}}})
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "source_format": "genie", "config_source": "startup"},
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_batfish_source_format_builds_interfaces(self) -> None:
        # Trimmed from a real batfish-extract-facts output for one node.
        node_facts = {
            "Interfaces": {
                "Ethernet0/0": {
                    "Active": True,
                    "Admin_Up": True,
                    "All_Prefixes": ["192.168.178.120/24", "192.168.178.240/24"],
                    "Description": "xxx",
                    "MTU": 1500,
                    "Primary_Address": "192.168.178.240/24",
                },
                "Ethernet0/2": {
                    "Active": False,
                    "Admin_Up": False,
                    "All_Prefixes": [],
                    "Description": "test",
                    "MTU": 1500,
                    "Primary_Address": None,
                },
            }
        }
        device = _device(
            "dev-1",
            parsed={"batfish_extract_facts": {"parsed": node_facts, "error": None}},
        )
        outcomes = await execute(
            config={
                **_BASE_CONFIG,
                "source_format": "batfish",
                "parsed_key": "batfish_extract_facts",
            },
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        eth00 = by_name["Ethernet0/0"]
        self.assertEqual(eth00["status"], "Active")
        self.assertTrue(eth00["enabled"])
        self.assertEqual(eth00["mtu"], 1500)
        self.assertEqual(
            eth00["ip_addresses"],
            [
                {
                    "address": "192.168.178.240/24",
                    "namespace": "Global",
                },
                {
                    "address": "192.168.178.120/24",
                    "namespace": "Global",
                    "ip_role": "secondary",
                },
            ],
        )

        eth02 = by_name["Ethernet0/2"]
        self.assertEqual(eth02["status"], "Active")
        self.assertFalse(eth02["enabled"])
        self.assertNotIn("ip_addresses", eth02)

    async def test_batfish_source_format_rejects_startup_config_source(self) -> None:
        device = _device(
            "dev-1",
            parsed={"batfish_extract_facts": {"parsed": {"Interfaces": {}}, "error": None}},
        )
        with self.assertRaises(ValueError):
            await execute(
                config={
                    **_BASE_CONFIG,
                    "source_format": "batfish",
                    "parsed_key": "batfish_extract_facts",
                    "config_source": "startup",
                },
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_batfish_source_format_skips_device_with_error(self) -> None:
        failed_device = _device(
            "dev-1",
            parsed={
                "batfish_extract_facts": {
                    "parsed": None,
                    "error": "no facts found for node 'dev-1' in this Batfish snapshot",
                }
            },
        )
        ok_device = _device(
            "dev-2",
            parsed={
                "batfish_extract_facts": {
                    "parsed": {
                        "Interfaces": {
                            "Ethernet0/0": {"Active": True, "Admin_Up": True},
                        }
                    },
                    "error": None,
                }
            },
        )
        outcomes = await execute(
            config={
                **_BASE_CONFIG,
                "source_format": "batfish",
                "parsed_key": "batfish_extract_facts",
            },
            context=_context({"dev-1": failed_device, "dev-2": ok_device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        devices = outcomes[0].context.devices
        self.assertNotIn("nautobot", devices["dev-1"].attribute_bags)
        self.assertIn("nautobot", devices["dev-2"].attribute_bags)

    async def test_cisco_config_parser_l2_access_interfaces(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed_full(
                _parsed_model(
                    l2_access_interfaces=[
                        {
                            "name": "Ethernet0/0",
                            "data_vlan": "100",
                            "children": ["switchport access vlan 100"],
                        },
                        {
                            "name": "Ethernet0/3",
                            "data_vlan": "200",
                            "children": ["switchport access vlan 200"],
                        },
                    ],
                )
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertEqual(by_name["Ethernet0/0"]["mode"], "access")
        self.assertEqual(by_name["Ethernet0/0"]["untagged_vlan"], 100)
        self.assertEqual(by_name["Ethernet0/3"]["untagged_vlan"], 200)

    async def test_cisco_config_parser_l2_trunk_interfaces_with_vlan_range(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed_full(
                _parsed_model(
                    l2_trunk_interfaces=[
                        {
                            "name": "Ethernet0/4",
                            "allowed_vlans": "10,20,30-32",
                            "children": ["switchport trunk allowed vlan 10,20,30-32"],
                        },
                    ],
                )
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        eth04 = interfaces[0]
        self.assertEqual(eth04["mode"], "trunk")
        self.assertEqual(eth04["tagged_vlans"], [10, 20, 30, 31, 32])

    async def test_cisco_config_parser_port_channel_member_bug_mitigation(self) -> None:
        # Reproduces the real "switch" example: Ethernet0/2 is a channel-group-only
        # member with no IP and no switchport command, so cisco_config_parser omits
        # it from l3/l2_access/l2_trunk entirely — the same is true for
        # Port-channel10 itself (no IP, no switchport command on the bundle).
        device = _device(
            "dev-1",
            parsed=_parsed_full(
                _parsed_model(
                    l2_access_interfaces=[
                        {
                            "name": "Ethernet0/0",
                            "data_vlan": "100",
                            "children": ["switchport access vlan 100"],
                        },
                    ],
                    port_channels=[
                        {
                            "name": "Port-channel10",
                            "id": "10",
                            "description": "port-channel 10",
                            "protocol": "lacp",
                            "members": [{"interface": "Ethernet0/2", "mode": "active"}],
                        }
                    ],
                )
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        self.assertEqual(set(by_name), {"Ethernet0/0", "Ethernet0/2", "Port-channel10"})

        member = by_name["Ethernet0/2"]
        self.assertEqual(member["lag"], "Port-channel10")
        self.assertTrue(member["enabled"])
        self.assertEqual(member["status"], "Active")
        self.assertEqual(member["type"], "100base-tx")

        port_channel = by_name["Port-channel10"]
        self.assertEqual(port_channel["type"], "lag")
        self.assertEqual(port_channel["description"], "port-channel 10")
        self.assertTrue(port_channel["enabled"])

        # Unrelated l2_access interface is untouched.
        self.assertNotIn("lag", by_name["Ethernet0/0"])

    async def test_cisco_config_parser_port_channel_member_with_real_l3_config(self) -> None:
        # A member interface that also has real L3 config (LAB example's
        # Ethernet0/2, a member of Port-channel11) must keep its existing data
        # and just get lag merged on top, not be clobbered by a stub.
        device = _device(
            "dev-1",
            parsed=_parsed_full(
                _parsed_model(
                    l3_interfaces=[
                        {
                            "name": "Ethernet0/2",
                            "description": "portchannel",
                            "children": ["description portchannel", "shutdown"],
                        },
                    ],
                    port_channels=[
                        {
                            "name": "Port-channel11",
                            "id": "11",
                            "description": "port-channel 11",
                            "members": [{"interface": "Ethernet0/2", "mode": "active"}],
                        }
                    ],
                )
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}

        eth02 = by_name["Ethernet0/2"]
        self.assertEqual(eth02["description"], "portchannel")
        self.assertFalse(eth02["enabled"])  # preserved from real l3 data, not stub default
        self.assertEqual(eth02["lag"], "Port-channel11")

    async def test_cisco_config_parser_port_channel_falls_back_to_id_when_name_missing(
        self,
    ) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed_full(
                _parsed_model(
                    port_channels=[
                        {"id": "7", "members": [{"interface": "Ethernet0/9", "mode": "on"}]}
                    ],
                )
            ),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertIn("Port-channel7", by_name)
        self.assertEqual(by_name["Ethernet0/9"]["lag"], "Port-channel7")

    async def test_invalid_source_format_raises(self) -> None:
        device = _device("dev-1", parsed=_parsed({"name": "Ethernet0/0", "children": []}))
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "source_format": "bogus"},
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_capability_attributes_set(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed({"name": "Ethernet0/0", "children": []}),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertIn(Capability.ATTRIBUTES, outcomes[0].context.devices["dev-1"].capabilities)


class PrimaryIpv4SelectionTests(unittest.IsolatedAsyncioTestCase):
    def _iface(self, name: str, ip: str, mask: str = "255.255.255.0") -> dict:
        return {"name": name, "ip_address": ip, "mask": mask, "children": []}

    async def test_management_interface_selected_first(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
                self._iface("Mgmt0", "10.0.0.1"),
                self._iface("Loopback0", "1.1.1.1"),
            ),
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "update_primary_ipv4": True},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Mgmt0"]["ip_addresses"][0]["is_primary"])
        self.assertNotIn("is_primary", by_name["Loopback0"]["ip_addresses"][0])

    async def test_loopback_highest_selected_when_no_management(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
                self._iface("Loopback0", "1.1.1.1"),
                self._iface("Loopback100", "2.2.2.2"),
            ),
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "update_primary_ipv4": True},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Loopback100"]["ip_addresses"][0]["is_primary"])
        self.assertNotIn("is_primary", by_name["Loopback0"]["ip_addresses"][0])

    async def test_loopback_lowest_selected_when_priority_reordered(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
                self._iface("Loopback0", "1.1.1.1"),
                self._iface("Loopback100", "2.2.2.2"),
            ),
        )
        outcomes = await execute(
            config={
                **_BASE_CONFIG,
                "update_primary_ipv4": True,
                "primary_ipv4_priority": [
                    "loopback_lowest",
                    "loopback_highest",
                    "management_interface",
                    "custom_interface",
                ],
            },
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Loopback0"]["ip_addresses"][0]["is_primary"])
        self.assertNotIn("is_primary", by_name["Loopback100"]["ip_addresses"][0])

    async def test_custom_interface_regex_selected(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
                self._iface("Vlan1", "192.168.1.1"),
                self._iface("Vlan2", "192.168.2.1"),
            ),
        )
        outcomes = await execute(
            config={
                **_BASE_CONFIG,
                "update_primary_ipv4": True,
                "primary_ipv4_priority": [
                    "custom_interface",
                    "management_interface",
                    "loopback_highest",
                    "loopback_lowest",
                ],
                "primary_ipv4_custom_pattern": r"^Vlan1$",
            },
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Vlan1"]["ip_addresses"][0]["is_primary"])
        self.assertNotIn("is_primary", by_name["Vlan2"]["ip_addresses"][0])

    async def test_no_strategy_matches_routes_to_failure(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(self._iface("Ethernet0/0", "10.0.0.5")),
        )
        outcomes = await execute(
            config={**_BASE_CONFIG, "update_primary_ipv4": True},
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(outcomes[0].name, "success")
        self.assertNotIn("dev-1", outcomes[0].context.devices)
        self.assertEqual(outcomes[1].name, "failure")
        failed = outcomes[1].context.devices["dev-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "primary_ipv4_not_found")
        # Interfaces are still written even though primary selection failed.
        self.assertIn("nautobot", failed.attribute_bags)

    async def test_invalid_priority_raises(self) -> None:
        device = _device("dev-1", parsed=_parsed(self._iface("Ethernet0/0", "10.0.0.5")))
        with self.assertRaises(ValueError):
            await execute(
                config={
                    **_BASE_CONFIG,
                    "update_primary_ipv4": True,
                    "primary_ipv4_priority": ["management_interface", "loopback_highest"],
                },
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_custom_pattern_raises(self) -> None:
        device = _device("dev-1", parsed=_parsed(self._iface("Ethernet0/0", "10.0.0.5")))
        with self.assertRaises(ValueError):
            await execute(
                config={
                    **_BASE_CONFIG,
                    "update_primary_ipv4": True,
                    "primary_ipv4_custom_pattern": "[unclosed",
                },
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_checkbox_off_preserves_existing_primary_when_present(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(
                self._iface("Mgmt0", "10.0.0.1"),
                self._iface("Loopback0", "1.1.1.1"),
            ),
            primary_ip4="1.1.1.1/32",
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(outcomes[0].name, "success")
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        by_name = {i["name"]: i for i in interfaces}
        self.assertTrue(by_name["Loopback0"]["ip_addresses"][0]["is_primary"])
        self.assertNotIn("is_primary", by_name["Mgmt0"]["ip_addresses"][0])

    async def test_checkbox_off_routes_to_failure_when_primary_missing(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(self._iface("Mgmt0", "10.0.0.1")),
            primary_ip4="9.9.9.9",
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(outcomes[1].name, "failure")
        failed = outcomes[1].context.devices["dev-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "primary_ipv4_not_found")

    async def test_checkbox_off_no_known_primary_passes_through_unmarked(self) -> None:
        device = _device(
            "dev-1",
            parsed=_parsed(self._iface("Mgmt0", "10.0.0.1")),
        )
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context({"dev-1": device}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(outcomes[0].name, "success")
        interfaces = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"]
        self.assertNotIn("is_primary", interfaces[0]["ip_addresses"][0])


if __name__ == "__main__":
    unittest.main()
