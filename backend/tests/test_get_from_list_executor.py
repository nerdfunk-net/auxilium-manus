"""Tests for the get-from-list step executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceStatus, WorkflowContext
from workflow_steps.get_from_list.executor import execute


class GetFromListExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_builds_devices_from_static_list(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"

        outcomes = await execute(
            config={
                "devices": ["router1", "switch2", "router1"],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="get-from-list-1",
        )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        self.assertEqual(len(outcome.context.devices), 2)

        devices = list(outcome.context.devices.values())
        names = sorted(device.name for device in devices)
        self.assertEqual(names, ["router1", "switch2"])

        for device in devices:
            self.assertEqual(device.source, "list")
            self.assertEqual(device.source_id, "get-from-list-1")
            self.assertEqual(device.hostname, device.name)
            self.assertEqual(device.status, DeviceStatus.OK)
            self.assertIn(Capability.IDENTITY, device.capabilities)

        self.assertEqual(outcome.context.metadata["get-from-list-1.total"], 2)
        self.assertEqual(
            outcome.context.metadata["get-from-list-1.devices"],
            ["router1", "switch2"],
        )

    async def test_execute_requires_at_least_one_device(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"

        with self.assertRaises(ValueError):
            await execute(
                config={"devices": ["", "  "]},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="get-from-list-1",
            )

    async def test_execute_sets_fan_out_metadata_when_enabled(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = "run-1"

        outcomes = await execute(
            config={
                "devices": ["router1"],
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
            node_id="get-from-list-1",
        )

        fan_out = outcomes[0].context.metadata["_fan_out"]
        self.assertTrue(fan_out["enabled"])
        self.assertEqual(fan_out["mode"], "chunked")
        self.assertEqual(fan_out["chunk_size"], 2)
        self.assertEqual(fan_out["max_concurrency"], 4)
        self.assertEqual(fan_out["inventory_node_id"], "get-from-list-1")


if __name__ == "__main__":
    unittest.main()
