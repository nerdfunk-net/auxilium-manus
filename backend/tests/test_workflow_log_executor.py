"""Tests for workflow-log executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.common.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.workflow_log.executor import execute


class WorkflowLogExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_configured_attributes_per_device(self) -> None:
        run = MagicMock()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "message": "Check role",
                "attribute_paths": [
                    "device.name",
                    "device.network_driver",
                    "nautobot.role.name",
                    "status",
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-1",
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, context.devices)

        debug_logs = outcomes[0].context.metadata[f"workflow-log-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["message"], "Check role")
        self.assertEqual(debug_logs["device_count"], 1)
        values = debug_logs["devices"]["device-1"]["values"]
        self.assertEqual(values["device.name"], "lab")
        self.assertEqual(values["device.network_driver"], "cisco_ios")
        self.assertEqual(values["nautobot.role.name"], "access-switch")
        self.assertEqual(values["status"], "ok")

    async def test_passes_through_when_no_devices(self) -> None:
        run = MagicMock()
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={})

        outcomes = await execute(
            config={"attribute_paths": ["device.name"]},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-2",
        )

        self.assertEqual(outcomes[0].context.devices, {})
        debug_logs = outcomes[0].context.metadata[f"workflow-log-2{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["device_count"], 0)
        self.assertEqual(debug_logs["devices"], {})

    async def test_requires_attribute_paths(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(id="device-1", name="lab", hostname="lab"),
            },
        )

        with self.assertRaises(ValueError):
            await execute(
                config={"attribute_paths": []},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="workflow-log-3",
            )


if __name__ == "__main__":
    unittest.main()
