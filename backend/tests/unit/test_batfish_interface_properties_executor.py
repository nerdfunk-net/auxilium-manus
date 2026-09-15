"""Tests for batfish-interface-properties executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_interface_properties.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_interface_properties.executor.service_factory"


def _context_with_snapshot() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishInterfacePropertiesExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_stores_result(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.interface_properties = AsyncMock(
                return_value=[
                    {
                        "Interface": {"hostname": "lab", "interface": "GigabitEthernet0/1"},
                        "Description": "uplink",
                    }
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"nodes": "lab", "properties": "Description"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].name, "success")
        result = outcomes[0].context.metadata["node-1.batfish_interface_properties"]
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["question"], "interfaceProperties")

        self.assertEqual(outcomes[1].name, "devices")
        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"lab"})
        device = devices["lab"]
        self.assertEqual(device.id, "lab")
        self.assertEqual(device.source, "batfish")
        self.assertEqual(device.capabilities, {Capability.IDENTITY})
        self.assertEqual(device.status, DeviceStatus.OK)

    async def test_config_fields_map_to_interface_properties_kwargs(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.interface_properties = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={
                    "nodes": "lab",
                    "interfaces": "GigabitEthernet0/1",
                    "properties": "Description, MTU",
                },
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.interface_properties.call_args
        self.assertEqual(kwargs["nodes"], "lab")
        self.assertEqual(kwargs["interfaces"], "GigabitEthernet0/1")
        self.assertEqual(kwargs["properties"], "Description, MTU")
        self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
        self.assertEqual(kwargs["snapshot"], "run-42")

    async def test_dedupes_devices_across_multiple_interfaces_on_same_node(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.interface_properties = AsyncMock(
                return_value=[
                    {"Interface": {"hostname": "lab", "interface": "Gi0/1"}, "MTU": 1500},
                    {"Interface": {"hostname": "lab", "interface": "Gi0/2"}, "MTU": 1500},
                    {"Interface": {"hostname": "lab-2", "interface": "Gi0/1"}, "MTU": 1500},
                ]
            )
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
        self.assertEqual(set(devices_outcome.context.devices), {"lab", "lab-2"})
        self.assertEqual(devices_outcome.summary, "2 device(s)")

    async def test_route_empty_to_devices_any_mode_filters_to_empty_interfaces(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.interface_properties = AsyncMock(
                return_value=[
                    {"Interface": {"hostname": "lab", "interface": "Gi0/1"}, "Description": "wan"},
                    {"Interface": {"hostname": "lab-2", "interface": "Gi0/1"}, "Description": ""},
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"properties": "Description", "route_empty_to_devices": True},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        devices_outcome = next(outcome for outcome in outcomes if outcome.name == "devices")
        self.assertEqual(set(devices_outcome.context.devices), {"lab-2"})

    async def test_route_empty_to_devices_all_mode(self) -> None:
        run = MagicMock()
        run.id = 42
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.interface_properties = AsyncMock(
                return_value=[
                    {
                        "Interface": {"hostname": "lab", "interface": "Gi0/1"},
                        "Description": "",
                        "Primary_Address": "10.0.0.1/24",
                    },
                    {
                        "Interface": {"hostname": "lab-2", "interface": "Gi0/1"},
                        "Description": "",
                        "Primary_Address": None,
                    },
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "properties": "Description, Primary_Address",
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
            batfish.interface_properties = AsyncMock(return_value=[])
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

        _, kwargs = batfish.interface_properties.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-99")


if __name__ == "__main__":
    unittest.main()
