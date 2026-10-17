"""Tests for compare-data executor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.compare_data.executor import execute


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


class ReferencePathContainmentTests(unittest.TestCase):
    def test_reference_subdirectory_cannot_escape_data_dir(self) -> None:
        from workflow_steps.compare_data.reference_reader import _filesystem_reference_path

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            data.mkdir()
            (base / "secret.env").write_text("SECRET")
            with patch("workflow_steps.compare_data.reference_reader.settings") as cfg:
                cfg.data_directory = data
                for sub in ("../", "..", "../..", "a/../.."):
                    with self.subTest(sub=sub), self.assertRaises(ValueError):
                        _filesystem_reference_path(
                            reference_subdirectory=sub, relative_path="secret.env"
                        )

    def test_git_reference_through_symlink_is_refused(self) -> None:
        from core.domain_exceptions import AccessDeniedError
        from workflow_steps.compare_data.reference_reader import _git_reference_path

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            repo = base / "repo"
            repo.mkdir()
            (base / "secret.env").write_text("SECRET")
            (repo / "link.env").symlink_to(base / "secret.env")
            with (
                patch(
                    "workflow_steps.compare_data.reference_reader.get_repo_path", return_value=repo
                ),
                self.assertRaises(AccessDeniedError),
            ):
                _git_reference_path(
                    repository={"name": "r"}, repository_subdirectory="", relative_path="link.env"
                )


class CompareDataExecutorTests(unittest.IsolatedAsyncioTestCase):
    def test_trailing_newline_ignored_with_ignore_trailing_whitespace(self) -> None:
        from workflow_steps.compare_data.executor import _normalize_text

        kwargs = dict(normalize_line_endings=True, ignore_trailing_whitespace=True)
        self.assertEqual(_normalize_text("a\nb\n", **kwargs), _normalize_text("a\nb", **kwargs))

    def test_trailing_newline_still_differs_when_option_off(self) -> None:
        from workflow_steps.compare_data.executor import _normalize_text

        kwargs = dict(normalize_line_endings=True, ignore_trailing_whitespace=False)
        self.assertNotEqual(_normalize_text("a\nb\n", **kwargs), _normalize_text("a\nb", **kwargs))

    async def test_match_routes_to_match_outcome(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab\n",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp) / "references"
            ref_dir.mkdir()
            (ref_dir / "lab.cfg").write_text("hostname lab\n", encoding="utf-8")

            with (
                patch("workflow_steps.compare_data.reference_reader.settings") as settings_mock,
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab\n"),
                ),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "running_config",
                        "reference_location": "filesystem",
                        "reference_subdirectory": "references",
                        "filename_template": "{device.name}.cfg",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="compare-data-1",
                    device_sessions=MagicMock(),
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name), {"match", "mismatch", "failure"})
        self.assertEqual(list(by_name["match"].context.devices), ["device-1"])
        self.assertEqual(by_name["mismatch"].context.devices, {})
        self.assertEqual(by_name["failure"].context.devices, {})

        comparison = (
            by_name["match"].context.devices["device-1"].parsed["compare-data-1"]["comparison"]
        )
        self.assertTrue(comparison["matched"])
        counts = by_name["match"].context.metadata["compare-data-1.comparison_counts"]
        self.assertEqual(counts["match"], 1)

    async def test_mismatch_routes_to_mismatch_outcome_and_stores_diff(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab-new\n",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp) / "references"
            ref_dir.mkdir()
            (ref_dir / "lab.cfg").write_text("hostname lab-old\n", encoding="utf-8")

            with (
                patch("workflow_steps.compare_data.reference_reader.settings") as settings_mock,
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab-new\n"),
                ),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "running_config",
                        "reference_location": "filesystem",
                        "reference_subdirectory": "references",
                        "filename_template": "{device.name}.cfg",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="compare-data-1",
                    device_sessions=MagicMock(),
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["device-1"])
        comparison = (
            by_name["mismatch"].context.devices["device-1"].parsed["compare-data-1"]["comparison"]
        )
        self.assertFalse(comparison["matched"])
        self.assertIn("diff_stats", comparison)
        self.assertEqual(comparison["comparison_diff_key"], "parsed.compare-data-1.comparison_diff")

        diff_entry = (
            by_name["mismatch"]
            .context.devices["device-1"]
            .parsed["compare-data-1"]["comparison_diff"]
        )
        self.assertEqual(diff_entry["kind"], "comparison_diff")
        self.assertIn("artifact_ref", diff_entry)
        diff_text = await artifact_service.resolve(
            ArtifactRef.model_validate(diff_entry["artifact_ref"])
        )
        self.assertIn("---", diff_text)

    async def test_pyats_snapshot_mismatch_stores_text_diff(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content='{"bgp": {"success": true, "data": {"peers": 2}}}',
            kind="pyats_snapshot",
            device_id="device-1",
            run_id="run-uuid-1",
            media_type="application/json",
        )
        device = _device_with_pyats_snapshot()

        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp) / "references"
            ref_dir.mkdir()
            (ref_dir / "lab.json").write_text(
                '{"bgp": {"success": true, "data": {"peers": 1}}}', encoding="utf-8"
            )

            with (
                patch("workflow_steps.compare_data.reference_reader.settings") as settings_mock,
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value='{"bgp": {"success": true, "data": {"peers": 2}}}'),
                ),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "pyats_snapshot",
                        "source_step_node_id": "get-pyats-snapshot-5",
                        "parsed_output_key": "pyats_snapshot",
                        "reference_location": "filesystem",
                        "reference_subdirectory": "references",
                        "filename_template": "{device.name}.json",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="compare-data-1",
                    device_sessions=MagicMock(),
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["device-1"])
        comparison = (
            by_name["mismatch"].context.devices["device-1"].parsed["compare-data-1"]["comparison"]
        )
        self.assertFalse(comparison["matched"])
        self.assertEqual(comparison["content_source"], "pyats_snapshot")

    async def test_missing_reference_file_routes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 42
        artifact_service = InMemoryArtifactService()
        await artifact_service.store(
            content="hostname lab\n",
            kind="running_config",
            device_id="device-1",
            run_id="run-uuid-1",
        )
        device = _device_with_running_config()

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("workflow_steps.compare_data.reference_reader.settings") as settings_mock,
                patch.object(
                    artifact_service,
                    "resolve",
                    new=AsyncMock(return_value="hostname lab\n"),
                ),
            ):
                settings_mock.data_directory = Path(tmp)

                outcomes = await execute(
                    config={
                        "content_source": "running_config",
                        "reference_location": "filesystem",
                        "reference_subdirectory": "references",
                        "filename_template": "{device.name}.cfg",
                    },
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id="compare-data-1",
                    device_sessions=MagicMock(),
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["device-1"])
        failed_device = by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed_device.status, DeviceStatus.FAILED)

    async def test_multiple_command_outputs_fail_the_device(self) -> None:
        from models.workflow_context import CommandResult

        artifact_service = InMemoryArtifactService()
        refs = [
            await artifact_service.store(
                content=text, kind="command_output", device_id="device-1", run_id="run-uuid-1"
            )
            for text in ("one\n", "two\n")
        ]
        device = DeviceContext(
            id="device-1",
            name="router1",
            hostname="router1",
            command_results={
                "run-1": [
                    CommandResult(
                        node_id="run-1", command="show a", success=True, output_ref=refs[0]
                    ),
                    CommandResult(
                        node_id="run-1", command="show b", success=True, output_ref=refs[1]
                    ),
                ]
            },
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={
                "content_source": "command_output",
                "source_step_node_id": "run-1",
                "reference_location": "filesystem",
                "filename_template": "{device.name}.cfg",
            },
            context=WorkflowContext(
                run_id="run-uuid-1", workflow_id="wf-1", devices={"device-1": device}
            ),
            run=MagicMock(id=1),
            artifact_service=artifact_service,
            node_id="compare-data-1",
            device_sessions=MagicMock(),
        )
        failed = {o.name: o for o in outcomes}["failure"].context.devices["device-1"]
        self.assertEqual(failed.errors[-1].code, "ambiguous_content")
        self.assertEqual(failed.errors[-1].failure.kind, "ambiguous_match")


if __name__ == "__main__":
    unittest.main()
