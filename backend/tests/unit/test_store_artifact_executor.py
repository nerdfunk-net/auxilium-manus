"""Tests for store-artifact executor."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.artifacts.sinks import GitArtifactSink
from workflow_steps.store_artifact.executor import execute


@contextmanager
def _mock_export_directory(export_dir: Path):
    """Patch the general-settings lookup `execute()` performs before building a sink."""
    service_mock = MagicMock()
    service_mock.resolved_export_directory.return_value = export_dir
    with (
        patch("workflow_steps.store_artifact.executor.get_db_session", return_value=MagicMock()),
        patch(
            "workflow_steps.store_artifact.executor.GeneralSettingsService",
            return_value=service_mock,
        ),
    ):
        yield


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


def _device_with_rendered_template() -> DeviceContext:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-rendered",
        kind="rendered_template",
        size_bytes=24,
    )
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        parsed={
            "device_config": {
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": "render-jinja-template-3",
                "output_key": "device_config",
                "size_bytes": 24,
                "kind": "rendered_template",
            }
        },
        capabilities={Capability.IDENTITY, Capability.PARSED},
        status=DeviceStatus.OK,
    )


def _device_with_pyats_snapshot() -> DeviceContext:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-snapshot",
        kind="pyats_snapshot",
        media_type="application/json",
        size_bytes=42,
    )
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        parsed={
            "pyats_snapshot": {
                "kind": "pyats_snapshot",
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": "get-pyats-snapshot-5",
                "features": {"bgp": {"success": True, "error": None}},
            }
        },
        capabilities={Capability.IDENTITY, Capability.PARSED},
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
            with (
                _mock_export_directory(Path(tmp)),
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab"),
                ),
            ):
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
                    device_sessions=MagicMock(),
                )

            export_file = Path(tmp) / "exports" / "wf-1" / "run-uuid-1" / "DC1" / "lab.cfg"
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
            with (
                _mock_export_directory(Path(tmp)),
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab"),
                ),
            ):
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
                    device_sessions=MagicMock(),
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

    async def test_exports_rendered_template_to_filesystem(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab\ninterface Gi0/0",
            kind="rendered_template",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        device = _device_with_rendered_template()

        with tempfile.TemporaryDirectory() as tmp:
            with (
                _mock_export_directory(Path(tmp)),
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab\ninterface Gi0/0"),
                ),
            ):
                outcomes = await execute(
                    config={
                        "content_source": "rendered_template",
                        "source_step_node_id": "render-jinja-template-3",
                        "parsed_output_key": "device_config",
                        "filename_template": "{device.name}_{parsed.output_key}.txt",
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
                    device_sessions=MagicMock(),
                )

            export_root = Path(tmp) / "exports" / "wf-1" / "run-uuid-1"
            files = list(export_root.glob("*.txt"))
            self.assertEqual(len(files), 1)
            self.assertEqual(
                files[0].read_text(encoding="utf-8"),
                "hostname lab\ninterface Gi0/0",
            )
            self.assertEqual(files[0].name, "lab_device_config.txt")

        self.assertEqual(len(outcomes), 1)
        stored = outcomes[0].context.metadata["store-artifact-4.stored_artifacts"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["content_source"], "rendered_template")
        self.assertEqual(stored[0]["output_key"], "device_config")

    async def test_exports_pyats_snapshot_to_filesystem(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content='{"bgp": {"success": true, "data": {}}}',
            kind="pyats_snapshot",
            device_id="device-1",
            run_id="run-uuid-1",
            media_type="application/json",
        )
        device = _device_with_pyats_snapshot()

        with tempfile.TemporaryDirectory() as tmp:
            with (
                _mock_export_directory(Path(tmp)),
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value='{"bgp": {"success": true, "data": {}}}'),
                ),
            ):
                outcomes = await execute(
                    config={
                        "content_source": "pyats_snapshot",
                        "source_step_node_id": "get-pyats-snapshot-5",
                        "parsed_output_key": "pyats_snapshot",
                        "filename_template": "{device.name}_{parsed.output_key}.json",
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
                    device_sessions=MagicMock(),
                )

            export_root = Path(tmp) / "exports" / "wf-1" / "run-uuid-1"
            files = list(export_root.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "lab_pyats_snapshot.json")

        self.assertEqual(len(outcomes), 1)
        stored = outcomes[0].context.metadata["store-artifact-4.stored_artifacts"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["content_source"], "pyats_snapshot")
        self.assertEqual(stored[0]["output_key"], "pyats_snapshot")

    async def test_strict_template_failure_goes_to_failure_outcome(self) -> None:
        run = MagicMock()
        run.id = 42
        device = _device_with_running_config()
        device = device.model_copy(update={"attribute_bags": {}})

        artifact_service = InMemoryArtifactService()
        with (
            patch.object(
                artifact_service,
                "resolve",
                new=AsyncMock(return_value="hostname lab"),
            ),
            tempfile.TemporaryDirectory() as tmp,
            _mock_export_directory(Path(tmp)),
        ):
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
                device_sessions=MagicMock(),
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
            with _mock_export_directory(Path(tmp)):
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
                    device_sessions=MagicMock(),
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

        with (
            patch(
                "workflow_steps.store_artifact.executor._build_sink",
                return_value=mock_sink,
            ),
            _mock_export_directory(Path("/unused")),
        ):
            outcomes = await execute(
                config={
                    "destination": "git",
                    "git_repository_id": 7,
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
                device_sessions=MagicMock(),
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

        with (
            patch(
                "workflow_steps.store_artifact.executor._build_sink",
                return_value=mock_sink,
            ),
            patch.object(
                artifact_service,
                "resolve",
                new=AsyncMock(return_value="hostname lab"),
            ),
            _mock_export_directory(Path("/unused")),
        ):
            outcomes = await execute(
                config={
                    "destination": "git",
                    "git_repository_id": 7,
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
                device_sessions=MagicMock(),
            )

        mock_sink.finalize.assert_awaited_once()
        self.assertEqual(len(outcomes), 1)
        self.assertNotIn("store-artifact-4.git_export", outcomes[0].context.metadata)

    async def test_rejects_escaping_output_subdirectory(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(ValueError) as ctx:
                    await execute(
                        config={
                            "destination": "filesystem",
                            "output_subdirectory": "../escape",
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
                        node_id="store-artifact-escape",
                        device_sessions=MagicMock(),
                    )
        self.assertIn("output_subdirectory", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
