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
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
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
                device_sessions=MagicMock(),
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

    async def test_resolves_credential_scoped_to_triggering_user(self) -> None:
        run = MagicMock()
        run.id = 1
        run.uuid = "run-uuid-1"
        run.triggered_by_id = 42
        db = MagicMock()
        run.__class__ = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ) as resolve_mock,
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            await execute(
                config={"credential_reference": "lab-ssh", "config_format": "both"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        resolve_mock.assert_called_once_with(db, "lab-ssh", acting_user_id=42)

    async def test_device_without_host_goes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
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
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[1].name, "failure")
        self.assertIn("device-1", outcomes[1].context.devices)

    async def test_retry_backoff_seconds_passed_through_to_get_configs(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "config_format": "both",
                    "retry_backoff_seconds": [10, 20, 30],
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        retry_policy = netmiko.get_configs.call_args.kwargs["retry"]
        self.assertEqual(retry_policy.backoff_seconds, (10, 20, 30))
        self.assertEqual(retry_policy.max_attempts, 4)

    async def test_retry_backoff_seconds_defaults_to_no_retry(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            await execute(
                config={"credential_reference": "lab-ssh", "config_format": "both"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        retry_policy = netmiko.get_configs.call_args.kwargs["retry"]
        self.assertEqual(retry_policy.backoff_seconds, ())
        self.assertEqual(retry_policy.max_attempts, 1)

    async def test_retry_backoff_seconds_out_of_bounds_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "config_format": "both",
                    "retry_backoff_seconds": [0],
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_read_timeout_passed_through_to_get_configs(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "config_format": "both",
                    "read_timeout": 200,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(netmiko.get_configs.call_args.kwargs["read_timeout"], 200)

    async def test_read_timeout_defaults_to_120(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.get_device_configs.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.get_device_configs.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.get_device_configs.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.get_configs = AsyncMock(
                return_value=ConfigResult(
                    success=True,
                    running_config="running cfg",
                    startup_config="startup cfg",
                )
            )

            await execute(
                config={"credential_reference": "lab-ssh", "config_format": "both"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(netmiko.get_configs.call_args.kwargs["read_timeout"], 120)

    async def test_read_timeout_out_of_bounds_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "config_format": "both",
                    "read_timeout": 1,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )


if __name__ == "__main__":
    unittest.main()
