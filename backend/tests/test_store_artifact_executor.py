"""Tests for store-artifact executor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.artifacts.sinks import GitArtifactSink
from workflow_steps.store_artifact.executor import execute


def _device_with_running_config() -> DeviceContext:
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        running_config_ref=ArtifactRef(
            artifact_id="artifact-running",
            kind="running_config",
            size_bytes=12,
        ),
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
        status=DeviceStatus.OK,
    )


class StoreArtifactExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_exports_running_config_to_nested_path(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "workflow_steps.store_artifact.executor.settings"
            ) as settings_mock, patch.object(
                artifact_service,
                "resolve",
                new=AsyncMock(return_value="hostname lab"),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "running_config",
                        "filename_template": "./{nautobot.location.name}/{device.name}.cfg",
                        "output_subdirectory": "exports",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="store-artifact-4",
                )

            export_file = (
                Path(tmp) / "exports" / "wf-1" / "run-uuid-1" / "DC1" / "lab.cfg"
            )
            self.assertTrue(export_file.is_file())
            self.assertEqual(export_file.read_text(encoding="utf-8"), "hostname lab")

        self.assertEqual(len(outcomes), 1)
        stored = outcomes[0].context.metadata["store-artifact-4.stored_artifacts"]
        self.assertEqual(len(stored), 1)
        self.assertIn("/DC1/lab.cfg", stored[0]["path"])

    async def test_exports_running_config_to_filesystem(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        # Re-use the in-memory store by patching resolve
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "workflow_steps.store_artifact.executor.settings"
            ) as settings_mock, patch.object(
                artifact_service,
                "resolve",
                new=AsyncMock(return_value="hostname lab"),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "running_config",
                        "filename_template": "{device.name}_{nautobot.location.name}.cfg",
                        "output_subdirectory": "exports",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="store-artifact-4",
                )

            export_root = Path(tmp) / "exports" / "wf-1" / "run-uuid-1"
            files = list(export_root.glob("*.cfg"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_text(encoding="utf-8"), "hostname lab")
            self.assertEqual(files[0].name, "lab_DC1.cfg")

        self.assertEqual(len(outcomes), 1)
        stored = outcomes[0].context.metadata["store-artifact-4.stored_artifacts"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["destination"], "filesystem")

    async def test_strict_template_failure_goes_to_failure_outcome(self) -> None:
        run = MagicMock()
        run.id = 42
        device = _device_with_running_config()
        device = device.model_copy(update={"attribute_bags": {}})

        artifact_service = InMemoryArtifactService()
        with patch.object(
            artifact_service,
            "resolve",
            new=AsyncMock(return_value="hostname lab"),
        ), tempfile.TemporaryDirectory() as tmp, patch(
            "workflow_steps.store_artifact.executor.settings"
        ) as settings_mock:
            settings_mock.data_directory = Path(tmp)
            outcomes = await execute(
                config={
                    "content_source": "running_config",
                    "filename_template": "{device.name}_{nautobot.location.name}.cfg",
                    "strict_templates": True,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="store-artifact-4",
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[1].name, "failure")
        self.assertIn(
            "get-nautobot-attributes",
            outcomes[1].context.devices["device-1"].errors[-1].message,
        )

    async def test_missing_content_goes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 42
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            status=DeviceStatus.OK,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("workflow_steps.store_artifact.executor.settings") as settings_mock:
                settings_mock.data_directory = Path(tmp)
                outcomes = await execute(
                    config={"content_source": "running_config"},
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="store-artifact-4",
                )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[1].name, "failure")

    async def test_git_prepare_failure_fails_all_devices(self) -> None:
        run = MagicMock()
        run.id = 42
        device = _device_with_running_config()
        artifact_service = InMemoryArtifactService()

        mock_sink = create_autospec(GitArtifactSink, instance=True)
        mock_sink.destination = "git"
        mock_sink.prepare = AsyncMock(side_effect=RuntimeError("pull failed"))
        mock_sink.has_writes = False

        with patch(
            "workflow_steps.store_artifact.executor._build_sink",
            return_value=mock_sink,
        ):
            outcomes = await execute(
                config={
                    "destination": "git",
                    "git_source_id": "prod-configs",
                    "content_source": "running_config",
                    "pull_before_write": True,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="store-artifact-4",
            )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[1].name, "failure")
        self.assertIn("pull failed", outcomes[1].context.devices["device-1"].errors[-1].message)

    async def test_git_write_only_skips_finalize(self) -> None:
        run = MagicMock()
        run.id = 42
        device = _device_with_running_config()
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )

        mock_sink = create_autospec(GitArtifactSink, instance=True)
        mock_sink.destination = "git"
        mock_sink.prepare = AsyncMock()
        mock_sink.finalize = AsyncMock(return_value=None)
        mock_sink.has_writes = True
        mock_sink.write_text = AsyncMock(
            return_value=MagicMock(
                destination="git",
                path="/tmp/repo/lab.cfg",
                size_bytes=12,
                sha256="abc",
            )
        )

        with patch(
            "workflow_steps.store_artifact.executor._build_sink",
            return_value=mock_sink,
        ), patch.object(
            artifact_service,
            "resolve",
            new=AsyncMock(return_value="hostname lab"),
        ):
            outcomes = await execute(
                config={
                    "destination": "git",
                    "git_source_id": "prod-configs",
                    "content_source": "running_config",
                    "filename_template": "{device.name}.cfg",
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="store-artifact-4",
            )

        mock_sink.finalize.assert_awaited_once()
        self.assertEqual(len(outcomes), 1)
        self.assertNotIn("store-artifact-4.git_export", outcomes[0].context.metadata)


if __name__ == "__main__":
    unittest.main()
