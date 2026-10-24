"""Tests for the set-default-attributes step executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.set_default_attributes.config import get_config
from workflow_steps.set_default_attributes.executor import execute


def _device(device_id: str, *, nautobot_bag: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        source="list",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags={"nautobot": nautobot_bag} if nautobot_bag is not None else {},
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = "run-1"
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


class SetDefaultAttributesManualModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_seeds_empty_bag(self) -> None:
        config = {
            **get_config(),
            "attributes": {
                **get_config()["attributes"],
                "role": {"enabled": True, "value": "Network"},
                "status": {"enabled": True, "value": "Active"},
            },
        }
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": _device("dev-1")}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})
        self.assertEqual(device.attribute_bags["nautobot"]["status"], {"name": "Active"})
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)

    async def test_seeds_secrets_group(self) -> None:
        config = {
            **get_config(),
            "attributes": {
                **get_config()["attributes"],
                "secrets_group": {"enabled": True, "value": "ssh-creds"},
            },
        }
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": _device("dev-1")}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["secrets_group"], {"name": "ssh-creds"})

    async def test_git_mode_seeds_secrets_group(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_repository_id": 1, "filename_pattern": "*.yaml"},
        }
        with patch(
            "workflow_steps.set_default_attributes.executor.load_yaml_from_git_source",
            return_value={"devices": {"secrets_group": "ssh-creds"}},
        ):
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["secrets_group"], {"name": "ssh-creds"})

    async def test_overwrite_false_skips_existing_value(self) -> None:
        config = {
            **get_config(),
            "overwrite": False,
            "attributes": {
                **get_config()["attributes"],
                "role": {"enabled": True, "value": "Network"},
            },
        }
        existing = _device("dev-1", nautobot_bag={"role": {"name": "Existing"}})
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": existing}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Existing"})

    async def test_flag_given_as_string_false(self) -> None:
        config = {
            **get_config(),
            "overwrite": "false",  # the string "false" used to count as true
            "attributes": {
                **get_config()["attributes"],
                "role": {"enabled": True, "value": "Network"},
            },
        }
        existing = _device("dev-1", nautobot_bag={"role": {"name": "Existing"}})
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": existing}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Existing"})

    async def test_overwrite_true_replaces_existing_value(self) -> None:
        config = {
            **get_config(),
            "overwrite": True,
            "attributes": {
                **get_config()["attributes"],
                "role": {"enabled": True, "value": "Network"},
            },
        }
        existing = _device("dev-1", nautobot_bag={"role": {"name": "Existing"}})
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": existing}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})

    async def _run_interface_type(
        self,
        bag: dict | None,
        *,
        interface_type: str = "1000base-t",
        overwrite: bool = False,
        interfaces: list | None = None,
    ) -> dict:
        base = get_config()["attributes"]
        config = {
            **get_config(),
            "overwrite": overwrite,
            "attributes": {
                **base,
                "interface_type": {"enabled": True, "value": interface_type},
                "interfaces": interfaces or [],
            },
        }
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": _device("dev-1", nautobot_bag=bag)}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        return outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]

    async def test_interface_type_fills_missing_type_and_keeps_other_fields(self) -> None:
        iface = {
            "name": "eth0",
            "description": "uplink",
            "ip_addresses": [
                {"address": "10.0.0.1/24", "parent": {"namespace": {"name": "black"}}}
            ],
        }
        bag = await self._run_interface_type({"name": "d1", "interfaces": [iface]})
        self.assertEqual(bag["interfaces"], [{**iface, "type": "1000base-t"}])
        self.assertNotIn("interface_type", bag)

    async def test_interface_type_keeps_existing_type(self) -> None:
        bag = await self._run_interface_type(
            {"interfaces": [{"name": "lo0", "type": "virtual"}, {"name": "eth0"}]}
        )
        self.assertEqual(
            bag["interfaces"],
            [{"name": "lo0", "type": "virtual"}, {"name": "eth0", "type": "1000base-t"}],
        )

    async def test_interface_type_blank_existing_type_is_filled(self) -> None:
        bag = await self._run_interface_type({"interfaces": [{"name": "eth0", "type": "  "}]})
        self.assertEqual(bag["interfaces"][0]["type"], "1000base-t")

    async def test_interface_type_overwrite_replaces_only_the_type(self) -> None:
        bag = await self._run_interface_type(
            {"interfaces": [{"name": "lo0", "type": "virtual", "description": "x"}]},
            overwrite=True,
        )
        self.assertEqual(
            bag["interfaces"], [{"name": "lo0", "type": "1000base-t", "description": "x"}]
        )

    async def test_interface_type_without_interfaces_is_noop(self) -> None:
        bag = await self._run_interface_type({"name": "d1"})
        self.assertEqual(bag, {"name": "d1"})

    async def test_interface_type_covers_interfaces_added_by_defaults(self) -> None:
        bag = await self._run_interface_type(
            {"interfaces": [{"name": "eth0"}]},
            interfaces=[{"name": "Loopback0"}, {"name": "mgmt0", "type": "other"}],
        )
        types = {i["name"]: i["type"] for i in bag["interfaces"]}
        self.assertEqual(types, {"eth0": "1000base-t", "Loopback0": "1000base-t", "mgmt0": "other"})

    async def test_interface_type_does_not_mutate_input_bag(self) -> None:
        original = {"interfaces": [{"name": "eth0"}]}
        await self._run_interface_type(original)
        self.assertEqual(original, {"interfaces": [{"name": "eth0"}]})

    async def test_interface_type_disabled_does_nothing(self) -> None:
        base = get_config()["attributes"]
        config = {
            **get_config(),
            "attributes": {**base, "interface_type": {"enabled": False, "value": "virtual"}},
        }
        outcomes = await execute(
            config=config,
            context=_context(
                {"dev-1": _device("dev-1", nautobot_bag={"interfaces": [{"name": "eth0"}]})}
            ),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["interfaces"], [{"name": "eth0"}])

    async def test_device_type_and_custom_fields_and_interfaces(self) -> None:
        config = {
            **get_config(),
            "attributes": {
                **get_config()["attributes"],
                "device_type": {"enabled": True, "model": "", "manufacturer": "Cisco"},
                "custom_fields": {"net": {"enabled": True, "value": "lab"}},
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "type": "VIRTUAL",
                        "status": "Active",
                        "ip_addresses": ["192.168.178.240/24"],
                    }
                ],
            },
        }
        outcomes = await execute(
            config=config,
            context=_context({"dev-1": _device("dev-1")}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["device_type"], {"manufacturer": {"name": "Cisco"}})
        self.assertEqual(bag["custom_fields"], {"net": "lab"})
        self.assertEqual(
            bag["interfaces"],
            [
                {
                    "name": "Ethernet0/0",
                    "type": "VIRTUAL",
                    "status": {"name": "Active"},
                    "ip_addresses": [{"address": "192.168.178.240/24"}],
                }
            ],
        )

    async def test_no_devices_is_noop(self) -> None:
        config = {
            **get_config(),
            "attributes": {
                **get_config()["attributes"],
                "role": {"enabled": True, "value": "Network"},
            },
        }
        outcomes = await execute(
            config=config,
            context=_context({}),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_unsupported_type_raises(self) -> None:
        config = {**get_config(), "type": "ip_address"}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_mode_raises(self) -> None:
        config = {**get_config(), "mode": "bogus"}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )


class SetDefaultAttributesGitModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_git_mode_merges_parsed_devices_block(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_repository_id": 7, "filename_pattern": "defaults.yaml"},
        }
        with patch(
            "workflow_steps.set_default_attributes.executor.load_yaml_from_git_source",
            return_value={"devices": {"role": "Network", "status": "Active"}},
        ) as mocked:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        mocked.assert_called_once_with(
            git_repository_id=7,
            filename_pattern="defaults.yaml",
            step_id="set-default-attributes",
            directory="",
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})
        self.assertEqual(device.attribute_bags["nautobot"]["status"], {"name": "Active"})

    async def test_git_mode_missing_devices_key_raises(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_repository_id": 7, "filename_pattern": "defaults.yaml"},
        }
        with patch(
            "workflow_steps.set_default_attributes.executor.load_yaml_from_git_source",
            return_value={"not_devices": {}},
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config=config,
                    context=_context({"dev-1": _device("dev-1")}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_git_mode_propagates_loader_error(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_repository_id": None, "filename_pattern": ""},
        }
        with patch(
            "workflow_steps.set_default_attributes.executor.load_yaml_from_git_source",
            side_effect=ValueError(
                "set-default-attributes: git_repository_id is not configured"
            ),
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config=config,
                    context=_context({"dev-1": _device("dev-1")}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
