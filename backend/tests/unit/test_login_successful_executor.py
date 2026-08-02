"""Tests for login-successful executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.login_successful.executor import execute


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


class LoginSuccessfulExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_login_routes_to_success(self) -> None:
        run = MagicMock()
        run.id = 1
        run.uuid = "run-uuid-1"
        run.triggered_by_id = 7
        db = MagicMock()
        with (
            patch(
                "workflow_steps.login_successful.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.login_successful.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ) as resolve_mock,
            patch("workflow_steps.login_successful.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.test_login = AsyncMock(return_value=True)

            outcomes = await execute(
                config={"credential_reference": "lab-ssh"},
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

        resolve_mock.assert_called_once_with(db, "lab-ssh", acting_user_id=7)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertIn("device-1", outcomes[0].context.devices)
        self.assertEqual(outcomes[1].context.devices, {})
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIn(Capability.PARSED, device.capabilities)
        self.assertTrue(device.parsed["node-1.login"]["login_ok"])

    async def test_failed_login_routes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = None
        db = MagicMock()
        with (
            patch(
                "workflow_steps.login_successful.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.login_successful.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.login_successful.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.test_login = AsyncMock(side_effect=RuntimeError("Authentication failed"))

            outcomes = await execute(
                config={"credential_reference": "lab-ssh"},
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

        self.assertEqual(outcomes[0].context.devices, {})
        self.assertIn("device-1", outcomes[1].context.devices)
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertFalse(failed.parsed["node-1.login"]["login_ok"])
        self.assertEqual(failed.errors[-1].code, "runtimeerror")

    async def test_device_without_host_goes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = None
        db = MagicMock()
        with (
            patch(
                "workflow_steps.login_successful.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.login_successful.executor.resolve_ssh_credential",
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
            outcomes = await execute(
                config={"credential_reference": "lab-ssh"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].context.devices, {})
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.errors[-1].code, "missing_host")

    async def test_missing_credential_raises(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = None
        db = MagicMock()
        with (
            patch(
                "workflow_steps.login_successful.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.login_successful.executor.resolve_ssh_credential",
                side_effect=ValueError("credential_reference is not configured"),
            ),
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config={"credential_reference": ""},
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

    async def test_network_driver_override_passed_to_netmiko(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = None
        db = MagicMock()
        with (
            patch(
                "workflow_steps.login_successful.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.login_successful.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.login_successful.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.test_login = AsyncMock(return_value=True)

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "network_driver_override": "cisco_nxos",
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

        netmiko.test_login.assert_awaited_once()
        kwargs = netmiko.test_login.await_args.kwargs
        self.assertEqual(kwargs["device_type"], "cisco_nxos")

    async def test_empty_devices_returns_both_outcomes(self) -> None:
        outcomes = await execute(
            config={"credential_reference": "lab-ssh"},
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=MagicMock(),
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])


if __name__ == "__main__":
    unittest.main()
