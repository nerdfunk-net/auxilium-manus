"""Tests for batfish-bgp-facts executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_bgp_facts.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_bgp_facts.executor.service_factory"


def _context_with_snapshot() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


def _mock_batfish() -> MagicMock:
    batfish = MagicMock()
    batfish.bgp_process_configuration = AsyncMock(
        return_value=[{"Node": "r1", "VRF": "default"}]
    )
    batfish.bgp_peer_configuration = AsyncMock(
        return_value=[{"Node": "r1", "Remote_AS": "200"}]
    )
    batfish.bgp_session_status = AsyncMock(
        return_value=[{"Node": "r1", "Remote_Node": "r2", "Established_Status": "ESTABLISHED"}]
    )
    batfish.bgp_edges = AsyncMock(
        return_value=[{"Node": "r1", "Remote_Node": "r2", "AS_Number": "100"}]
    )
    return batfish


class BatfishBgpFactsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_all_four_questions_enabled_by_default(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = _mock_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        batfish.bgp_process_configuration.assert_awaited_once()
        batfish.bgp_peer_configuration.assert_awaited_once()
        batfish.bgp_session_status.assert_awaited_once()
        batfish.bgp_edges.assert_awaited_once()

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[1].name, "devices")
        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r1"})
        parsed_r1 = devices["r1"].parsed["node-1.batfish_bgp_facts"]["parsed"]
        self.assertIn("Process", parsed_r1)
        self.assertIn("Peers", parsed_r1)
        self.assertIn("Sessions", parsed_r1)
        self.assertIn("Adjacencies", parsed_r1)

    async def test_disabled_questions_are_not_queried(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = _mock_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"include_peers": False, "include_edges": False},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        batfish.bgp_process_configuration.assert_awaited_once()
        batfish.bgp_session_status.assert_awaited_once()
        batfish.bgp_peer_configuration.assert_not_awaited()
        batfish.bgp_edges.assert_not_awaited()

        metadata = outcomes[0].context.metadata
        self.assertIn("node-1.batfish_bgp_facts.process", metadata)
        self.assertIn("node-1.batfish_bgp_facts.sessions", metadata)
        self.assertNotIn("node-1.batfish_bgp_facts.peers", metadata)
        self.assertNotIn("node-1.batfish_bgp_facts.edges", metadata)

    async def test_all_questions_disabled_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={
                        "include_process": False,
                        "include_peers": False,
                        "include_sessions": False,
                        "include_edges": False,
                    },
                    context=_context_with_snapshot(),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_nodes_filter_applied_to_every_enabled_question(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = _mock_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"nodes": "R1"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        for mock_call in (
            batfish.bgp_process_configuration,
            batfish.bgp_peer_configuration,
            batfish.bgp_session_status,
            batfish.bgp_edges,
        ):
            _, kwargs = mock_call.call_args
            self.assertEqual(kwargs["nodes"], "R1")
            self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
            self.assertEqual(kwargs["snapshot"], "run-42")

    async def test_missing_snapshot_metadata_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={},
                    context=WorkflowContext(run_id="run-uuid-1", workflow_id="7"),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_explicit_source_and_network_bypasses_metadata(self) -> None:
        run = MagicMock()
        run.id = 1
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")

        with (
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
            patch(
                "workflow_steps.common.batfish_context.object_session",
                return_value=MagicMock(),
            ),
            patch(
                "workflow_steps.common.batfish_context.BatfishSourceConfigService"
            ) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            batfish = _mock_batfish()
            batfish.list_networks = AsyncMock(return_value=["manus-production"])
            batfish.list_snapshots_with_metadata = AsyncMock(
                return_value=[
                    {"name": "run-99", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}}
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.bgp_process_configuration.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-99")


if __name__ == "__main__":
    unittest.main()
