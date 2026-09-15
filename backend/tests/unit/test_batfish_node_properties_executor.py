"""Tests for batfish-node-properties executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_node_properties.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_node_properties.executor.service_factory"


def _context_with_snapshot() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishNodePropertiesExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_stores_result(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[{"Node": "r1", "TACACS_Servers": ["10.0.0.5"]}]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"nodes": "R1", "properties": "TACACS_Servers"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].name, "success")
        result = outcomes[0].context.metadata["node-1.batfish_node_properties"]
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["question"], "nodeProperties")

        self.assertEqual(outcomes[1].name, "devices")
        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r1"})
        device = devices["r1"]
        self.assertEqual(device.id, "r1")
        self.assertEqual(device.source, "batfish")
        self.assertEqual(device.capabilities, {Capability.IDENTITY})
        self.assertEqual(device.status, DeviceStatus.OK)

    async def test_config_fields_map_to_node_properties_kwargs(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"nodes": "R1", "properties": "TACACS_Servers, TACACS_Source_Interface"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.node_properties.call_args
        self.assertEqual(kwargs["nodes"], "R1")
        self.assertEqual(kwargs["properties"], "TACACS_Servers, TACACS_Source_Interface")
        self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
        self.assertEqual(kwargs["snapshot"], "run-42")

    async def test_blank_properties_omitted(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.node_properties.call_args
        self.assertIsNone(kwargs["properties"])
        self.assertIsNone(kwargs["nodes"])

    async def test_devices_outcome_emitted_when_no_rows_match(self) -> None:
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

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(devices_outcome.context.devices, {})
        self.assertEqual(devices_outcome.summary, "0 device(s)")

    async def test_route_empty_to_devices_disabled_keeps_every_node(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[
                    {"Node": "lab", "TACACS_Servers": ["ISE_SERVER_1"]},
                    {"Node": "lab-2", "TACACS_Servers": []},
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"properties": "TACACS_Servers"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(set(devices_outcome.context.devices), {"lab", "lab-2"})

    async def test_route_empty_to_devices_any_mode_filters_to_empty_nodes(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[
                    {"Node": "lab", "TACACS_Servers": ["ISE_SERVER_1"]},
                    {"Node": "lab-2", "TACACS_Servers": []},
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"properties": "TACACS_Servers", "route_empty_to_devices": True},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(set(devices_outcome.context.devices), {"lab-2"})
        self.assertEqual(devices_outcome.summary, "1 device(s)")

    async def test_route_empty_to_devices_any_mode_flags_if_one_of_several_is_empty(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[
                    {
                        "Node": "lab",
                        "TACACS_Servers": ["ISE_SERVER_1"],
                        "TACACS_Source_Interface": "",
                    },
                    {
                        "Node": "lab-2",
                        "TACACS_Servers": ["ISE_SERVER_1"],
                        "TACACS_Source_Interface": "Loopback0",
                    },
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "properties": "TACACS_Servers, TACACS_Source_Interface",
                    "route_empty_to_devices": True,
                    "empty_match_mode": "any",
                },
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(set(devices_outcome.context.devices), {"lab"})

    async def test_route_empty_to_devices_all_mode_requires_every_property_empty(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.node_properties = AsyncMock(
                return_value=[
                    {"Node": "lab", "TACACS_Servers": [], "TACACS_Source_Interface": "Loopback0"},
                    {"Node": "lab-2", "TACACS_Servers": [], "TACACS_Source_Interface": ""},
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "properties": "TACACS_Servers, TACACS_Source_Interface",
                    "route_empty_to_devices": True,
                    "empty_match_mode": "all",
                },
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(set(devices_outcome.context.devices), {"lab-2"})

    async def test_route_empty_to_devices_without_properties_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={"route_empty_to_devices": True},
                    context=_context_with_snapshot(),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_invalid_empty_match_mode_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={
                        "properties": "TACACS_Servers",
                        "route_empty_to_devices": True,
                        "empty_match_mode": "bogus",
                    },
                    context=_context_with_snapshot(),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

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
            batfish = MagicMock()
            batfish.list_networks = AsyncMock(return_value=["manus-production"])
            batfish.node_properties = AsyncMock(return_value=[])
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

        _, kwargs = batfish.node_properties.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-99")


if __name__ == "__main__":
    unittest.main()
