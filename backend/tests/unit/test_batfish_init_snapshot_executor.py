"""Tests for batfish-init-snapshot executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_init_snapshot.executor import execute

_CONFIG_SERVICE_TARGET = "workflow_steps.batfish_init_snapshot.executor.BatfishSourceConfigService"
_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_init_snapshot.executor.service_factory"
_OBJECT_SESSION_TARGET = "workflow_steps.batfish_init_snapshot.executor.object_session"


async def _device_with_running_config(
    artifact_service: InMemoryArtifactService,
    device_id: str = "device-1",
    text: str = "hostname R1\n",
) -> DeviceContext:
    ref = await artifact_service.store(
        content=text, kind="running_config", device_id=device_id, run_id="1"
    )
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        running_config_ref=ref,
        status=DeviceStatus.OK,
    )


def _device_without_running_config(device_id: str = "device-2") -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id, status=DeviceStatus.OK)


class BatfishInitSnapshotExecutorTests(unittest.IsolatedAsyncioTestCase):
    def _run_mock(self) -> MagicMock:
        run = MagicMock()
        run.id = 42
        return run

    async def test_happy_path_stores_snapshot_metadata(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_running_config(artifact_service)
        run = self._run_mock()
        db = MagicMock()

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="batfish", port=9996
            )
            batfish = MagicMock()
            batfish.init_snapshot = AsyncMock(return_value="run-42")
            batfish.list_snapshots_with_metadata = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"batfish_source_id": "lab-batfish", "retain_snapshots": 5},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="7", devices={"device-1": device}
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        batfish.init_snapshot.assert_called_once()
        _, kwargs = batfish.init_snapshot.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-workflow-7")
        self.assertEqual(kwargs["snapshot_name"], "run-42")

        stored = outcomes[0].context.metadata["batfish"]
        self.assertEqual(stored["network"], "manus-workflow-7")
        self.assertEqual(stored["snapshot"], "run-42")
        self.assertEqual(stored["host"], "batfish")
        self.assertEqual(stored["port"], 9996)

    async def test_device_without_running_config_is_skipped_not_failed(self) -> None:
        artifact_service = InMemoryArtifactService()
        good_device = await _device_with_running_config(artifact_service, device_id="device-1")
        bad_device = _device_without_running_config(device_id="device-2")
        run = self._run_mock()

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="batfish", port=9996
            )
            batfish = MagicMock()
            batfish.init_snapshot = AsyncMock(return_value="run-42")
            batfish.list_snapshots_with_metadata = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"batfish_source_id": "lab-batfish"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="7",
                    devices={"device-1": good_device, "device-2": bad_device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")
        self.assertIn("1 skipped", outcomes[0].summary or "")

    async def test_all_devices_without_running_config_raises_runtime_error(self) -> None:
        run = self._run_mock()
        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET),
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="batfish", port=9996
            )
            with self.assertRaises(RuntimeError):
                await execute(
                    config={"batfish_source_id": "lab-batfish"},
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="7",
                        devices={"device-2": _device_without_running_config()},
                    ),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_missing_batfish_source_id_raises_value_error(self) -> None:
        run = self._run_mock()
        artifact_service = InMemoryArtifactService()
        device = await _device_with_running_config(artifact_service)
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="7", devices={"device-1": device}
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_retention_sweep_deletes_oldest_by_timestamp_not_name(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_running_config(artifact_service)
        run = self._run_mock()

        # Deliberately out of lexical-name order: "run-9" is newer than "run-10"
        # by timestamp, so a name-sort would wrongly delete "run-10" instead.
        entries = [
            {"name": "run-10", "metadata": {"creationTimestamp": "2026-09-12T10:00:00.000Z"}},
            {"name": "run-9", "metadata": {"creationTimestamp": "2026-09-12T12:00:00.000Z"}},
            {"name": "run-42", "metadata": {"creationTimestamp": "2026-09-12T14:00:00.000Z"}},
        ]

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="batfish", port=9996
            )
            batfish = MagicMock()
            batfish.init_snapshot = AsyncMock(return_value="run-42")
            batfish.list_snapshots_with_metadata = AsyncMock(return_value=entries)
            batfish.delete_snapshot = AsyncMock()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"batfish_source_id": "lab-batfish", "retain_snapshots": 2},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="7", devices={"device-1": device}
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        batfish.delete_snapshot.assert_called_once()
        _, kwargs = batfish.delete_snapshot.call_args
        self.assertEqual(kwargs["snapshot_name"], "run-10")

    async def test_retention_sweep_failure_is_swallowed(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_running_config(artifact_service)
        run = self._run_mock()

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="batfish", port=9996
            )
            batfish = MagicMock()
            batfish.init_snapshot = AsyncMock(return_value="run-42")
            batfish.list_snapshots_with_metadata = AsyncMock(
                side_effect=BatfishAPIError("coordinator unreachable")
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={"batfish_source_id": "lab-batfish", "retain_snapshots": 2},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="7", devices={"device-1": device}
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")


if __name__ == "__main__":
    unittest.main()
