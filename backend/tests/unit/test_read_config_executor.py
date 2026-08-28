"""Tests for read-config executor."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.read_config.executor import execute


@contextmanager
def _mock_export_directory(export_dir: Path):
    """Patch the general-settings lookup `execute()` performs for source=filesystem."""
    service_mock = MagicMock()
    service_mock.resolved_export_directory.return_value = export_dir
    with (
        patch("workflow_steps.read_config.executor.get_db_session", return_value=MagicMock()),
        patch(
            "workflow_steps.read_config.executor.GeneralSettingsService",
            return_value=service_mock,
        ),
    ):
        yield


@contextmanager
def _mock_git_repository(repo_dir: Path):
    """Patch repository lookup + clone_or_pull for source=git."""
    with (
        patch(
            "workflow_steps.read_config.executor.load_git_repository",
            return_value={
                "id": 7,
                "name": "prod-lab",
                "url": "https://example.invalid/repo.git",
            },
        ),
        patch(
            "workflow_steps.read_config.executor.clone_or_pull",
            return_value=repo_dir,
        ),
    ):
        yield


def _plain_device() -> DeviceContext:
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _device_with_running_config() -> DeviceContext:
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        running_config_ref=ArtifactRef(
            artifact_id="artifact-existing",
            kind="running_config",
            size_bytes=12,
        ),
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
        status=DeviceStatus.OK,
    )


class ReadConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_config_from_filesystem(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _plain_device()

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lab.cfg").write_text("hostname lab", encoding="utf-8")

            with _mock_export_directory(Path(tmp)):
                outcomes = await execute(
                    config={"source": "filesystem", "path_template": "{device.name}.cfg"},
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["device-1"]
        self.assertIsNotNone(updated.running_config_ref)
        self.assertIn(Capability.RUNNING_CONFIG, updated.capabilities)
        content = await artifact_service.resolve(updated.running_config_ref)
        self.assertEqual(content, "hostname lab")

    async def test_existing_running_config_left_unchanged_by_default(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lab.cfg").write_text("hostname new", encoding="utf-8")

            with _mock_export_directory(Path(tmp)):
                outcomes = await execute(
                    config={"source": "filesystem", "path_template": "{device.name}.cfg"},
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        self.assertEqual(len(outcomes), 1)
        updated = outcomes[0].context.devices["device-1"]
        self.assertEqual(updated.running_config_ref.artifact_id, "artifact-existing")

    async def test_overwrite_existing_replaces_running_config(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lab.cfg").write_text("hostname new", encoding="utf-8")

            with _mock_export_directory(Path(tmp)):
                outcomes = await execute(
                    config={
                        "source": "filesystem",
                        "path_template": "{device.name}.cfg",
                        "overwrite_existing": True,
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        updated = outcomes[0].context.devices["device-1"]
        self.assertNotEqual(updated.running_config_ref.artifact_id, "artifact-existing")
        content = await artifact_service.resolve(updated.running_config_ref)
        self.assertEqual(content, "hostname new")

    async def test_missing_file_fails_device(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _plain_device()

        with tempfile.TemporaryDirectory() as tmp:
            with _mock_export_directory(Path(tmp)):
                outcomes = await execute(
                    config={"source": "filesystem", "path_template": "{device.name}.cfg"},
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        names = {outcome.name for outcome in outcomes}
        self.assertEqual(names, {"success", "failure"})
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        failed_device = failure_outcome.context.devices["device-1"]
        self.assertEqual(failed_device.status, DeviceStatus.FAILED)
        self.assertEqual(failed_device.errors[-1].code, "filenotfounderror")

    async def test_unresolved_placeholder_fails_device(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with _mock_export_directory(Path(tmp)):
                outcomes = await execute(
                    config={
                        "source": "filesystem",
                        "path_template": "{nautobot.location.name}/{device.name}.cfg",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        self.assertIn("device-1", failure_outcome.context.devices)

    async def test_reads_config_from_git(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _plain_device()

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lab.cfg").write_text("hostname git-lab", encoding="utf-8")

            with _mock_git_repository(Path(tmp)):
                outcomes = await execute(
                    config={
                        "source": "git",
                        "git_repository_id": 7,
                        "path_template": "{device.name}.cfg",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="read-config-1",
                    device_sessions=MagicMock(),
                )

        self.assertEqual(len(outcomes), 1)
        updated = outcomes[0].context.devices["device-1"]
        content = await artifact_service.resolve(updated.running_config_ref)
        self.assertEqual(content, "hostname git-lab")

    async def test_empty_devices_is_a_noop(self) -> None:
        run = MagicMock()
        run.id = 42
        outcomes = await execute(
            config={"source": "filesystem", "path_template": "{device.name}.cfg"},
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="read-config-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

    async def test_git_source_required_when_source_is_git(self) -> None:
        run = MagicMock()
        run.id = 42
        with self.assertRaises(ValueError):
            await execute(
                config={"source": "git", "path_template": "{device.name}.cfg"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _plain_device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="read-config-1",
                device_sessions=MagicMock(),
            )


if __name__ == "__main__":
    unittest.main()
