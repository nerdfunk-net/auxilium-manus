"""Tests for the get-from-user step executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceStatus, WorkflowContext
from workflow_steps.get_from_user.executor import execute


class GetFromUserExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_builds_devices_from_run_input_text(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "router1\nswitch2\nrouter1\n"}

        outcomes = await execute(
            config={"device_param": "target_devices"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="get-from-user-1",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        self.assertEqual(len(outcome.context.devices), 2)

        devices = list(outcome.context.devices.values())
        names = sorted(device.name for device in devices)
        self.assertEqual(names, ["router1", "switch2"])

        for device in devices:
            self.assertEqual(device.source, "run_input")
            self.assertEqual(device.source_id, "get-from-user-1")
            self.assertEqual(device.hostname, device.name)
            self.assertEqual(device.status, DeviceStatus.OK)
            self.assertIn(Capability.IDENTITY, device.capabilities)
            # Must never pre-populate the reserved "run_input" attribute bag —
            # that would make seed_run_input_bag skip the real run inputs.
            self.assertNotIn("run_input", device.attribute_bags)
            self.assertIn("get_from_user", device.attribute_bags)

        self.assertEqual(outcome.context.metadata["get-from-user-1.total"], 2)
        self.assertEqual(
            sorted(outcome.context.metadata["get-from-user-1.devices"]),
            ["router1", "switch2"],
        )

    async def test_execute_parses_bare_ip_and_name_ip_pair_lines(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {
            "target_devices": "10.0.0.5\nrouter1.example.com,10.0.0.6\n\n  \n"
        }

        outcomes = await execute(
            config={"device_param": "target_devices"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="get-from-user-1",
            device_sessions=MagicMock(),
        )

        devices = {device.name: device for device in outcomes[0].context.devices.values()}
        self.assertEqual(len(devices), 2)

        ip_only = devices["10.0.0.5"]
        self.assertEqual(ip_only.primary_ip4, "10.0.0.5")
        self.assertEqual(ip_only.hostname, "10.0.0.5")

        name_and_ip = devices["router1.example.com"]
        self.assertEqual(name_and_ip.primary_ip4, "10.0.0.6")
        self.assertEqual(name_and_ip.hostname, "10.0.0.6")

    async def test_execute_requires_device_param_configured(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "router1"}

        with self.assertRaises(ValueError):
            await execute(
                config={"device_param": ""},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="get-from-user-1",
                device_sessions=MagicMock(),
            )

    async def test_execute_requires_run_input_present(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {}

        with self.assertRaises(ValueError):
            await execute(
                config={"device_param": "target_devices"},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="get-from-user-1",
                device_sessions=MagicMock(),
            )

    async def test_execute_requires_at_least_one_device(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "\n   \n"}

        with self.assertRaises(ValueError):
            await execute(
                config={"device_param": "target_devices"},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="get-from-user-1",
                device_sessions=MagicMock(),
            )

    async def test_execute_rejects_invalid_ip_in_name_ip_line(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "router1,not-an-ip"}

        with self.assertRaises(ValueError):
            await execute(
                config={"device_param": "target_devices"},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="get-from-user-1",
                device_sessions=MagicMock(),
            )

    async def test_execute_sets_fan_out_metadata_when_enabled(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "router1"}

        outcomes = await execute(
            config={
                "device_param": "target_devices",
                "fan_out": {
                    "enabled": True,
                    "mode": "chunked",
                    "chunk_size": 2,
                    "max_concurrency": 4,
                },
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="get-from-user-1",
            device_sessions=MagicMock(),
        )

        fan_out = outcomes[0].context.metadata["_fan_out"]
        self.assertTrue(fan_out["enabled"])
        self.assertEqual(fan_out["mode"], "chunked")
        self.assertEqual(fan_out["chunk_size"], 2)
        self.assertEqual(fan_out["max_concurrency"], 4)
        self.assertEqual(fan_out["inventory_node_id"], "get-from-user-1")
        self.assertEqual(
            fan_out["approval"],
            {"enabled": False, "batch_size": 1, "first_batch_auto": True},
        )

    async def test_execute_sets_fan_out_approval_metadata(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"
        run.run_inputs = {"target_devices": "router1"}

        outcomes = await execute(
            config={
                "device_param": "target_devices",
                "fan_out": {
                    "enabled": True,
                    "mode": "chunked",
                    "chunk_size": 10,
                    "approval": {
                        "enabled": True,
                        "batch_size": 2,
                        "first_batch_auto": False,
                    },
                },
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="get-from-user-1",
            device_sessions=MagicMock(),
        )

        approval = outcomes[0].context.metadata["_fan_out"]["approval"]
        self.assertEqual(
            approval,
            {"enabled": True, "batch_size": 2, "first_batch_auto": False},
        )


if __name__ == "__main__":
    unittest.main()
