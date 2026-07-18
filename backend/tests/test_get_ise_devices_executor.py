"""Tests for get-ise-devices executor (mocked ISE service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.ise.common.exceptions import ISENotFoundError
from services.ise.source_config_service import ISESourceNotFoundError
from workflow_steps.get_ise_devices.executor import execute


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context() -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1")


def _patches(device_service: MagicMock):
    source_config_service = MagicMock()
    source_config_service.resolve_credentials.return_value = MagicMock()
    return (
        patch(
            "workflow_steps.get_ise_devices.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "service_factory.build_ise_source_config_service",
            return_value=source_config_service,
        ),
        patch(
            "service_factory.build_ise_network_device_service",
            return_value=device_service,
        ),
    )


class GetIseDevicesExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_ise_source_id(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

    async def test_missing_required_field_per_query_mode_raises(self) -> None:
        device_service = MagicMock()
        base_config = {"ise_source_id": "lab-ise"}
        for query_mode in ("name", "cidr", "group"):
            with self.subTest(query_mode=query_mode):
                p1, p2, p3 = _patches(device_service)
                with p1, p2, p3, self.assertRaises(ValueError):
                    await execute(
                        config={**base_config, "query_mode": query_mode},
                        context=_context(),
                        run=_run(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="node-1",
                    )

    async def test_name_mode_found_and_missing_are_skipped(self) -> None:
        device_service = MagicMock()
        device_service.get_device_by_name = AsyncMock(
            side_effect=[
                {
                    "NetworkDevice": {
                        "id": "abc-1",
                        "name": "router1",
                        "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
                    }
                },
                ISENotFoundError("not found"),
            ]
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "name",
                    "device_names": ["router1", "missing-device"],
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        self.assertEqual(len(outcome.context.devices), 1)
        device = outcome.context.devices["abc-1"]
        self.assertEqual(device.name, "router1")
        self.assertEqual(device.primary_ip4, "10.0.0.1")
        self.assertIn(Capability.IDENTITY, device.capabilities)
        self.assertEqual(device.source, "ise")
        self.assertFalse(device.attribute_bags["ise"]["is_group_or_prefix"])

    async def test_group_mode_lists_then_fetches_detail(self) -> None:
        device_service = MagicMock()
        device_service.list_devices_by_group = AsyncMock(
            return_value={
                "SearchResult": {
                    "total": 2,
                    "resources": [
                        {"id": "id-1", "name": "router1"},
                        {"id": "id-2", "name": "router2"},
                    ],
                    "nextPage": None,
                }
            }
        )
        device_service.get_device = AsyncMock(
            side_effect=[
                {
                    "NetworkDevice": {
                        "id": "id-1",
                        "name": "router1",
                        "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
                    }
                },
                {
                    "NetworkDevice": {
                        "id": "id-2",
                        "name": "router2",
                        "NetworkDeviceIPList": [{"ipaddress": "10.0.0.2", "mask": 32}],
                    }
                },
            ]
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "group",
                    "group_name": "Location#All Locations#Building1",
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        device_service.list_devices_by_group.assert_called_once()
        self.assertEqual(device_service.get_device.await_count, 2)
        self.assertEqual(len(outcomes[0].context.devices), 2)

    async def test_cidr_host_mode_uses_exact_filter(self) -> None:
        device_service = MagicMock()
        device_service.list_devices = AsyncMock(
            return_value={
                "SearchResult": {
                    "total": 1,
                    "resources": [{"id": "id-1", "name": "router1"}],
                    "nextPage": None,
                }
            }
        )
        device_service.get_device = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "id": "id-1",
                    "name": "router1",
                    "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "cidr",
                    "cidr": "10.0.0.1/32",
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        device_service.list_devices.assert_called_once_with(filter_="ipaddress.EQ.10.0.0.1")
        self.assertEqual(len(outcomes[0].context.devices), 1)

    async def test_cidr_wide_prefix_filters_client_side(self) -> None:
        device_service = MagicMock()
        device_service.list_devices = AsyncMock(
            return_value={
                "SearchResult": {
                    "total": 2,
                    "resources": [
                        {"id": "id-1", "name": "router1"},
                        {"id": "id-2", "name": "router2"},
                    ],
                    "nextPage": None,
                }
            }
        )
        device_service.get_device = AsyncMock(
            side_effect=[
                {
                    "NetworkDevice": {
                        "id": "id-1",
                        "name": "router1",
                        "NetworkDeviceIPList": [{"ipaddress": "10.0.0.5", "mask": 24}],
                    }
                },
                {
                    "NetworkDevice": {
                        "id": "id-2",
                        "name": "router2",
                        "NetworkDeviceIPList": [{"ipaddress": "192.168.1.1", "mask": 32}],
                    }
                },
            ]
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "cidr",
                    "cidr": "10.0.0.0/24",
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        device_service.list_devices.assert_called_once_with(page=1, size=100)
        devices = outcomes[0].context.devices
        self.assertEqual(len(devices), 1)
        self.assertIn("id-1", devices)
        self.assertTrue(devices["id-1"].attribute_bags["ise"]["is_group_or_prefix"])

    async def test_resolve_to_devices_stub_logs_and_passes_through(self) -> None:
        device_service = MagicMock()
        device_service.get_device_by_name = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "id": "id-1",
                    "name": "subnet-group",
                    "NetworkDeviceIPList": [{"ipaddress": "10.0.0.0", "mask": 24}],
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3, self.assertLogs(
            "workflow_steps.get_ise_devices.executor", level="WARNING"
        ) as logs:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "name",
                    "device_names": ["subnet-group"],
                    "resolve_to_devices": True,
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        self.assertTrue(any("not implemented" in message for message in logs.output))
        devices = outcomes[0].context.devices
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices["id-1"].attribute_bags["ise"]["is_group_or_prefix"])

    async def test_unknown_source_raises_value_error(self) -> None:
        device_service = MagicMock()
        source_config_service = MagicMock()
        source_config_service.resolve_credentials.side_effect = ISESourceNotFoundError("missing")
        with patch(
            "workflow_steps.get_ise_devices.executor.object_session",
            return_value=MagicMock(),
        ), patch(
            "service_factory.build_ise_source_config_service",
            return_value=source_config_service,
        ), patch(
            "service_factory.build_ise_network_device_service",
            return_value=device_service,
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config={
                        "ise_source_id": "missing",
                        "query_mode": "name",
                        "device_names": ["x"],
                    },
                    context=_context(),
                    run=_run(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                )

    async def test_fan_out_metadata_stamped(self) -> None:
        device_service = MagicMock()
        device_service.get_device_by_name = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "id": "id-1",
                    "name": "router1",
                    "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "query_mode": "name",
                    "device_names": ["router1"],
                    "fan_out": {
                        "enabled": True,
                        "mode": "per_device",
                        "chunk_size": 1,
                        "max_concurrency": 0,
                    },
                },
                context=_context(),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        metadata = outcomes[0].context.metadata
        self.assertIn("_fan_out", metadata)
        self.assertEqual(metadata["_fan_out"]["inventory_node_id"], "node-1")


if __name__ == "__main__":
    unittest.main()
