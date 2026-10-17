"""Tests for add-pyats-testbed executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.workflow_context.secret_fields import unwrap_secret
from workflow_steps.add_pyats_testbed.executor import execute


def _device(device_id: str = "device-1") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        status=DeviceStatus.OK,
    )


class AddPyatsTestbedExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_testbed_bag_with_sealed_password(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = 42
        db = MagicMock()
        with (
            patch("workflow_steps.add_pyats_testbed.executor.object_session", return_value=db),
            patch(
                "workflow_steps.add_pyats_testbed.executor.resolve_generic_credential",
                return_value=("admin", "secret"),
            ) as resolve_mock,
        ):
            outcomes = await execute(
                config={
                    "pyats_source_id": "lab-pyats",
                    "credential_reference": "lab-cred",
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

        resolve_mock.assert_called_once_with(db, "lab-cred", acting_user_id=42)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

        device = outcomes[0].context.devices["device-1"]
        self.assertIn(Capability.PYATS_TESTBED, device.capabilities)
        bag = device.attribute_bags["pyats_testbed"]
        self.assertEqual(bag["pyats_source_id"], "lab-pyats")
        self.assertEqual(bag["host"], "10.0.0.1")
        self.assertEqual(bag["os"], "ios")
        self.assertEqual(bag["username"], "admin")
        self.assertEqual(unwrap_secret(bag["password"]), "secret")

    async def test_network_driver_override_used_for_os_resolution(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = None
        db = MagicMock()
        with (
            patch("workflow_steps.add_pyats_testbed.executor.object_session", return_value=db),
            patch(
                "workflow_steps.add_pyats_testbed.executor.resolve_generic_credential",
                return_value=("admin", "secret"),
            ),
        ):
            outcomes = await execute(
                config={
                    "pyats_source_id": "lab-pyats",
                    "credential_reference": "lab-cred",
                    "network_driver_override": "nxos",
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

        bag = outcomes[0].context.devices["device-1"].attribute_bags["pyats_testbed"]
        self.assertEqual(bag["os"], "nxos")

    async def test_missing_pyats_source_id_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={"credential_reference": "lab-cred"},
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

    async def test_missing_credential_reference_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={"pyats_source_id": "lab-pyats"},
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

    async def test_no_devices_short_circuits(self) -> None:
        run = MagicMock()
        outcomes = await execute(
            config={"pyats_source_id": "lab-pyats", "credential_reference": "lab-cred"},
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].context.devices, {})


if __name__ == "__main__":
    unittest.main()
