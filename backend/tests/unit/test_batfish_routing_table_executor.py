"""Tests for batfish-routing-table executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_routing_table.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_routing_table.executor.service_factory"


def _context_with_snapshot() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishRoutingTableExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_stores_result(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.routes = AsyncMock(return_value=[{"Node": "r1", "Network": "10.0.0.0/24"}])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"nodes": "R1"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        result = outcomes[0].context.metadata["node-1.batfish_routes"]
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["question"], "routes")

    async def test_missing_snapshot_metadata_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="7"),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_config_fields_map_to_routes_kwargs(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.routes = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={
                    "nodes": "R1",
                    "network_prefix": "192.168.1.0/24",
                    "prefix_match_type": "LONGEST_PREFIX_MATCH",
                    "protocols": "static",
                    "vrfs": "default",
                    "rib": "bgp",
                },
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.routes.call_args
        self.assertEqual(kwargs["nodes"], "R1")
        self.assertEqual(kwargs["prefixMatchType"], "LONGEST_PREFIX_MATCH")
        self.assertEqual(kwargs["protocols"], "static")
        self.assertEqual(kwargs["vrfs"], "default")
        self.assertEqual(kwargs["rib"], "bgp")
        # "network" here is pybatfish's own route-prefix filter (from config's
        # network_prefix), distinct from batfish_network (the Batfish network
        # name) -- see BatfishService.routes()'s docstring for the collision
        # this distinction avoids.
        self.assertEqual(kwargs["network"], "192.168.1.0/24")
        self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
        self.assertEqual(kwargs["snapshot"], "run-42")


if __name__ == "__main__":
    unittest.main()
