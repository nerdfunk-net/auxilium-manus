"""Tests for batfish-path-check executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_path_check.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_path_check.executor.service_factory"


def _context_with_snapshot(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices=devices or {})
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishPathCheckExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, rows: list[dict], config: dict | None = None):
        run = MagicMock()
        run.id = 1
        devices = {
            "device-1": DeviceContext(
                id="device-1", name="d1", hostname="d1", status=DeviceStatus.OK
            )
        }
        context = _context_with_snapshot(devices)

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.reachability = AsyncMock(return_value=rows)
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config=config or {"start_node": "R1"},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        return outcomes, batfish, context

    async def test_non_empty_rows_yields_reachable_and_passes_devices_through(self) -> None:
        outcomes, _, context = await self._run(rows=[{"Flow": "x"}])
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "reachable")
        self.assertEqual(outcomes[0].context.devices, context.devices)

    async def test_empty_rows_yields_not_reachable(self) -> None:
        outcomes, _, context = await self._run(rows=[])
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "not_reachable")
        self.assertEqual(outcomes[0].context.devices, context.devices)

    async def test_headers_passed_as_sibling_not_nested_in_path_constraints(self) -> None:
        _, batfish, _ = await self._run(
            rows=[], config={"start_node": "R1", "end_node": "R2", "dst_ips": "10.0.0.1"}
        )
        _, kwargs = batfish.reachability.call_args
        self.assertEqual(kwargs["pathConstraints"], {"startLocation": "R1", "endLocation": "R2"})
        self.assertNotIn("headers", kwargs["pathConstraints"])
        self.assertEqual(kwargs["headers"], {"dstIps": "10.0.0.1"})

    async def test_missing_start_node_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )


if __name__ == "__main__":
    unittest.main()
