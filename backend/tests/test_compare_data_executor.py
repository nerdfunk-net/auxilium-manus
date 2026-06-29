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


class CompareDataExecutorTests(unittest.IsolatedAsyncioTestCase):
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
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name), {"match", "mismatch", "failure"})
        self.assertEqual(list(by_name["match"].context.devices), ["device-1"])
        self.assertEqual(by_name["mismatch"].context.devices, {})
        self.assertEqual(by_name["failure"].context.devices, {})

        comparison = by_name["match"].context.devices["device-1"].parsed[
            "compare-data-1.comparison"
        ]
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
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["device-1"])
        comparison = by_name["mismatch"].context.devices["device-1"].parsed[
            "compare-data-1.comparison"
        ]
        self.assertFalse(comparison["matched"])
        self.assertIn("diff_stats", comparison)
        self.assertEqual(comparison["comparison_diff_key"], "compare-data-1.comparison_diff")

        diff_entry = by_name["mismatch"].context.devices["device-1"].parsed[
            "compare-data-1.comparison_diff"
        ]
        self.assertEqual(diff_entry["kind"], "comparison_diff")
        self.assertIn("artifact_ref", diff_entry)
        diff_text = await artifact_service.resolve(
            ArtifactRef.model_validate(diff_entry["artifact_ref"])
        )
        self.assertIn("---", diff_text)

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
                )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["device-1"])
        failed_device = by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed_device.status, DeviceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
