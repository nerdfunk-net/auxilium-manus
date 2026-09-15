"""Tests for batfish-extract-facts executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_extract_facts.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_extract_facts.executor.service_factory"


def _device(device_id: str, name: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=name, hostname=name, status=DeviceStatus.OK)


def _context_with_snapshot(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices=devices or {})
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishExtractFactsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self, *, facts: dict, devices: dict[str, DeviceContext], config: dict | None = None
    ):
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.extract_facts = AsyncMock(return_value=facts)
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config=config or {},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        return outcomes, batfish

    async def test_found_node_enriches_device_parsed(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        outcomes, _ = await self._run(
            facts={"version": "batfish_v0", "nodes": {"r1": {"Hostname": "r1"}}},
            devices=devices,
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        device = outcomes[0].context.devices["device-1"]
        entry = device.parsed["batfish_extract_facts"]
        self.assertEqual(entry["parsed"], {"Hostname": "r1"})
        self.assertIsNone(entry["error"])
        self.assertIn(Capability.PARSED, device.capabilities)

    async def test_missing_node_records_non_fatal_error(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        outcomes, _ = await self._run(
            facts={"version": "batfish_v0", "nodes": {}},
            devices=devices,
        )
        device = outcomes[0].context.devices["device-1"]
        entry = device.parsed["batfish_extract_facts"]
        self.assertIsNone(entry["parsed"])
        self.assertIn("r1", entry["error"])
        self.assertNotIn(Capability.PARSED, device.capabilities)

    async def test_blank_nodes_filter_defaults_to_context_devices(self) -> None:
        devices = {
            "device-1": _device("device-1", "R1"),
            "device-2": _device("device-2", "R2"),
        }
        _, batfish = await self._run(facts={"nodes": {}}, devices=devices)
        _, kwargs = batfish.extract_facts.call_args
        # Comma-joined, not "|"-joined -- a bare (non-"/regex/") nodeSpec
        # containing "|" is parsed by Batfish as one literal node name, not
        # an alternation, and matches nothing.
        self.assertEqual(kwargs["nodes"], "r1,r2")

    async def test_explicit_nodes_filter_passed_through(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        _, batfish = await self._run(
            facts={"nodes": {}}, devices=devices, config={"nodes_filter": "/.*/"}
        )
        _, kwargs = batfish.extract_facts.call_args
        self.assertEqual(kwargs["nodes"], "/.*/")

    async def test_metadata_records_row_count(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        outcomes, _ = await self._run(facts={"nodes": {"r1": {}, "r2": {}}}, devices=devices)
        summary = outcomes[0].context.metadata["node-1.batfish_extract_facts"]
        self.assertEqual(summary["question"], "extractFacts")
        self.assertEqual(summary["row_count"], 2)


if __name__ == "__main__":
    unittest.main()
