"""Tests for batfish-start-run executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.batfish_start_run.executor import execute


class BatfishStartRunExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_clears_devices_and_succeeds(self) -> None:
        device = DeviceContext(id="d1", name="d1", hostname="d1", status=DeviceStatus.OK)
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices={"d1": device})

        outcomes = await execute(
            config={},
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_no_op_when_already_empty(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")

        outcomes = await execute(
            config={},
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})


if __name__ == "__main__":
    unittest.main()
