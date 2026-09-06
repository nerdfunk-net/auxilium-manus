"""Tests for the read-from-file executor."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.domain_exceptions import AccessDeniedError
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.read_from_file.executor import execute


@contextmanager
def _mock_export_directory(export_dir: Path):
    service_mock = MagicMock()
    service_mock.resolved_export_directory.return_value = export_dir
    with (
        patch(
            "workflow_steps.read_from_file.executor.get_db_session",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.read_from_file.executor.GeneralSettingsService",
            return_value=service_mock,
        ),
    ):
        yield


@contextmanager
def _mock_git_repository(repo_dir: Path):
    with (
        patch(
            "workflow_steps.read_from_file.executor.load_git_repository",
            return_value={
                "id": 7,
                "name": "prod-lab",
                "url": "https://example.invalid/repo.git",
            },
        ),
        patch(
            "workflow_steps.read_from_file.executor.clone_or_pull",
            return_value=repo_dir,
        ),
    ):
        yield


def _device(device_id: str = "device-1", *, bags: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


async def _run_execute(config: dict, devices: dict[str, DeviceContext]):
    run = MagicMock()
    run.id = 42
    return await execute(
        config=config,
        context=_context(devices),
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="read-from-file-1",
        device_sessions=MagicMock(),
    )


class ReadFromFileExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_yaml_from_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "site.yaml").write_text("a: 1\nb:\n  c: 2\n", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {"source": "filesystem", "path": "site.yaml", "destination_path": "data"},
                    {"device-1": _device()},
                )
        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.attribute_bags["data"], {"a": 1, "b": {"c": 2}})
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)

    async def test_merges_json_from_filesystem_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "site.json").write_text('{"a": 1}', encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {"source": "filesystem", "path": "site.json", "destination_path": "data"},
                    {"device-1": _device()},
                )
        self.assertEqual(outcomes[0].context.devices["device-1"].attribute_bags["data"], {"a": 1})

    async def test_explicit_json_format_on_yaml_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "site.yaml").write_text('{"a": 1}', encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {
                        "source": "filesystem",
                        "path": "site.yaml",
                        "format": "json",
                        "destination_path": "data",
                    },
                    {"device-1": _device()},
                )
        self.assertEqual(outcomes[0].context.devices["device-1"].attribute_bags["data"], {"a": 1})

    async def test_destination_subpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("region: emea", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {"source": "filesystem", "path": "s.yaml", "destination_path": "data.site"},
                    {"device-1": _device()},
                )
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["data"],
            {"site": {"region": "emea"}},
        )

    async def test_overwrite_false_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("a: new\nb: 2", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {"source": "filesystem", "path": "s.yaml", "destination_path": "data"},
                    {"device-1": _device(bags={"data": {"a": "old", "keep": 1}})},
                )
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["data"],
            {"a": "old", "keep": 1, "b": 2},
        )

    async def test_overwrite_true_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("a: new\nb: 2", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {
                        "source": "filesystem",
                        "path": "s.yaml",
                        "destination_path": "data",
                        "overwrite": True,
                    },
                    {"device-1": _device(bags={"data": {"a": "old", "keep": 1}})},
                )
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["data"],
            {"a": "new", "keep": 1, "b": 2},
        )

    async def test_list_replaced_wholesale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("x: [9]", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {
                        "source": "filesystem",
                        "path": "s.yaml",
                        "destination_path": "data",
                        "overwrite": True,
                    },
                    {"device-1": _device(bags={"data": {"x": [1, 2, 3]}})},
                )
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["data"], {"x": [9]}
        )

    async def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _mock_export_directory(Path(tmp)):
            with self.assertRaises(FileNotFoundError):
                await _run_execute(
                    {"source": "filesystem", "path": "nope.yaml", "destination_path": "data"},
                    {"device-1": _device()},
                )

    async def test_invalid_yaml_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("a: [1, 2", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(ValueError):
                    await _run_execute(
                        {"source": "filesystem", "path": "s.yaml", "destination_path": "data"},
                        {"device-1": _device()},
                    )

    async def test_non_mapping_document_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(ValueError) as ctx:
                    await _run_execute(
                        {"source": "filesystem", "path": "s.yaml", "destination_path": "data"},
                        {"device-1": _device()},
                    )
        self.assertIn("mapping", str(ctx.exception))

    async def test_reads_from_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.json").write_text('{"region": "emea"}', encoding="utf-8")
            with _mock_git_repository(Path(tmp)):
                outcomes = await _run_execute(
                    {
                        "source": "git",
                        "git_repository_id": 7,
                        "path": "s.json",
                        "destination_path": "data",
                    },
                    {"device-1": _device()},
                )
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["data"], {"region": "emea"}
        )

    async def test_git_repository_id_required_for_git(self) -> None:
        with self.assertRaises(ValueError):
            await _run_execute(
                {"source": "git", "path": "s.yaml", "destination_path": "data"},
                {"device-1": _device()},
            )

    async def test_reserved_destination_rejected(self) -> None:
        for path in ("parsed.foo", "run_input.foo"):
            with self.assertRaises(ValueError):
                await _run_execute(
                    {"source": "filesystem", "path": "s.yaml", "destination_path": path},
                    {"device-1": _device()},
                )

    async def test_device_scalar_destination_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await _run_execute(
                {"source": "filesystem", "path": "s.yaml", "destination_path": "device.name"},
                {"device-1": _device()},
            )

    async def test_unsafe_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _mock_export_directory(Path(tmp)):
            with self.assertRaises(AccessDeniedError):
                await _run_execute(
                    {
                        "source": "filesystem",
                        "path": "../../etc/passwd",
                        "destination_path": "data",
                    },
                    {"device-1": _device()},
                )

    async def test_empty_devices_is_noop(self) -> None:
        outcomes = await _run_execute(
            {"source": "filesystem", "path": "s.yaml", "destination_path": "data"}, {}
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_multiple_devices_all_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s.yaml").write_text("region: emea", encoding="utf-8")
            with _mock_export_directory(Path(tmp)):
                outcomes = await _run_execute(
                    {"source": "filesystem", "path": "s.yaml", "destination_path": "data"},
                    {"device-1": _device("device-1"), "device-2": _device("device-2")},
                )
        devices = outcomes[0].context.devices
        self.assertEqual(devices["device-1"].attribute_bags["data"], {"region": "emea"})
        self.assertEqual(devices["device-2"].attribute_bags["data"], {"region": "emea"})


if __name__ == "__main__":
    unittest.main()
