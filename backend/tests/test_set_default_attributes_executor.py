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
        )

        self.assertEqual(len(outcomes), 1)
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})
        self.assertEqual(device.attribute_bags["nautobot"]["status"], {"name": "Active"})
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)

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
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})

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
            )


class SetDefaultAttributesGitModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_git_mode_merges_parsed_devices_block(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_source_id": "prod-lab", "filename_pattern": "defaults.yaml"},
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
            )

        mocked.assert_called_once_with(
            git_source_id="prod-lab",
            filename_pattern="defaults.yaml",
            step_id="set-default-attributes",
        )
        device = outcomes[0].context.devices["dev-1"]
        self.assertEqual(device.attribute_bags["nautobot"]["role"], {"name": "Network"})
        self.assertEqual(device.attribute_bags["nautobot"]["status"], {"name": "Active"})

    async def test_git_mode_missing_devices_key_raises(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_source_id": "prod-lab", "filename_pattern": "defaults.yaml"},
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
                )

    async def test_git_mode_propagates_loader_error(self) -> None:
        config = {
            **get_config(),
            "mode": "git",
            "git": {"git_source_id": "", "filename_pattern": ""},
        }
        with patch(
            "workflow_steps.set_default_attributes.executor.load_yaml_from_git_source",
            side_effect=ValueError("set-default-attributes: git_source_id is not configured"),
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config=config,
                    context=_context({"dev-1": _device("dev-1")}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="node-1",
                )


if __name__ == "__main__":
    unittest.main()
