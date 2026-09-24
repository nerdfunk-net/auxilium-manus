"""Tests for batfish-start-run executor ("Get from Batfish")."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_start_run.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_start_run.executor.service_factory"


def _context_with_snapshot(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices=devices or {})
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishStartRunPlaceholderTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_no_metadata_clears_devices_zero_batfish_calls(self) -> None:
        device = DeviceContext(id="d1", name="d1", hostname="d1", status=DeviceStatus.OK)
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices={"d1": device})

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            outcomes = await execute(
                config={},
                context=context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
            service_factory_mock.get_batfish_app_service.assert_not_called()

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


class BatfishStartRunDevicePopulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_present_queries_node_properties_and_replaces_devices(self) -> None:
        run = MagicMock()
        run.id = 42
        existing_device = DeviceContext(id="old", name="old", hostname="old")
        context = _context_with_snapshot({"old": existing_device})

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[{"Node": "r1"}, {"Node": "r2"}]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        devices = outcomes[0].context.devices
        # Replaces, not merges -- the pre-existing "old" device is gone.
        self.assertEqual(set(devices), {"r1", "r2"})
        device = devices["r1"]
        self.assertEqual(device.id, "r1")
        self.assertEqual(device.name, "r1")
        self.assertEqual(device.hostname, "r1")
        self.assertEqual(device.source, "batfish")
        self.assertEqual(device.capabilities, {Capability.IDENTITY})
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertEqual(outcomes[0].summary, "2 device(s)")

    async def test_zero_nodes_returned_is_success_not_error(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[0].summary, "0 device(s)")

    async def test_nodes_filter_threaded_through_to_query(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"nodes_filter": "/^r/"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.node_properties.call_args
        self.assertEqual(kwargs["nodes"], "/^r/")
        self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
        self.assertEqual(kwargs["snapshot"], "run-42")

    async def test_malformed_metadata_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 42
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7").model_copy(
            update={"metadata": {"batfish": {"not": "valid"}}}
        )

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={},
                    context=context,
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )


class BatfishStartRunDirectTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_target_bypasses_metadata(self) -> None:
        run = MagicMock()
        run.id = 1
        # Deliberately no metadata on this context -- proves the explicit
        # config path bypasses metadata entirely, not merely prefers it.
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
            batfish = MagicMock()
            batfish.list_networks = AsyncMock(return_value=["manus-production"])
            batfish.node_properties = AsyncMock(return_value=[{"Node": "r1"}])
            batfish.list_snapshots_with_metadata = AsyncMock(
                return_value=[
                    {"name": "run-99", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}}
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.node_properties.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-99")
        self.assertEqual(set(outcomes[0].context.devices), {"r1"})

    async def test_direct_target_nonexistent_network_raises_value_error(self) -> None:
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
            batfish = MagicMock()
            batfish.list_networks = AsyncMock(return_value=["some-other-network"])
            batfish.node_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            with self.assertRaises(ValueError):
                await execute(
                    config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                    context=context,
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )
            batfish.node_properties.assert_not_called()


if __name__ == "__main__":
    unittest.main()
