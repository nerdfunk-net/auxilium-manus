"""Tests for get-device-configs executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import ConfigResult
from workflow_steps.get_device_configs.executor import execute


def _device(device_id: str = "device-1") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class GetDeviceConfigsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_configs_and_adds_capabilities(self) -> None:
        run = MagicMock()
        run.id = 1
        run.uuid = "run-uuid-1"
        db = MagicMock()
        run.__class__ = MagicMock()
        with patch(
            "workflow_steps.get_device_configs.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.get_device_configs.executor.NetmikoService"
        ) as netmiko_cls:
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            context = WorkflowContext(
                run_id="run-uuid-1",
                workflow_id="wf-1",
                devices={"device-1": _device()},
            )
            artifact_service = InMemoryArtifactService()

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "config_format": "both",
                },
                context=context,
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0]
        self.assertEqual(success.name, "success")
        device = success.context.devices["device-1"]
        self.assertIn(Capability.RUNNING_CONFIG, device.capabilities)
        self.assertIn(Capability.STARTUP_CONFIG, device.capabilities)
        self.assertIsNotNone(device.running_config_ref)
        self.assertIsNotNone(device.startup_config_ref)

        running_text = await artifact_service.resolve(device.running_config_ref)
        self.assertEqual(running_text, "running cfg")

    async def test_device_without_host_goes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with patch(
            "workflow_steps.get_device_configs.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ):
            device = DeviceContext(
                id="device-1",
                name="router1",
                hostname="",
                capabilities={Capability.IDENTITY},
                status=DeviceStatus.OK,
            )
            context = WorkflowContext(
                run_id="run-uuid-1",
                workflow_id="wf-1",
                devices={"device-1": device},
            )

            outcomes = await execute(
                config={"credential_reference": "lab-ssh", "config_format": "running"},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[1].name, "failure")
        self.assertIn("device-1", outcomes[1].context.devices)


if __name__ == "__main__":
    unittest.main()
