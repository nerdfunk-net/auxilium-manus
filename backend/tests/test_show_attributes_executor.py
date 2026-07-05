"""Tests for show-attributes executor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.show_attributes.executor import (
    SHOW_ATTRIBUTES_METADATA_SUFFIX,
    build_context_snapshot,
    execute,
    format_pretty_text,
)


class ShowAttributesExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdout_json_includes_all_device_attributes(self) -> None:
        run = MagicMock()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
            attribute_bags={
                "nautobot": {"role": {"name": "access-switch"}},
                "git": {"source_file": "configs/lab.yaml"},
                "custom": {"location": "dc1"},
            },
            capabilities={Capability.IDENTITY, Capability.ATTRIBUTES},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
            metadata={"upstream.step": {"count": 1}},
        )

        with patch("workflow_steps.show_attributes.executor.logger") as mock_logger:
            outcomes = await execute(
                config={
                    "output_destination": "stdout",
                    "output_format": "json",
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="show-attributes-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        payload = outcomes[0].context.metadata[
            f"show-attributes-1{SHOW_ATTRIBUTES_METADATA_SUFFIX}"
        ]
        self.assertEqual(payload["output_destination"], "stdout")
        self.assertEqual(payload["device_count"], 1)
        snapshot = payload["snapshot"]
        device_snapshot = snapshot["devices"]["device-1"]
        self.assertEqual(device_snapshot["attribute_bags"]["nautobot"]["role"]["name"], "access-switch")
        self.assertEqual(device_snapshot["attribute_bags"]["git"]["source_file"], "configs/lab.yaml")
        self.assertEqual(device_snapshot["attribute_bags"]["custom"]["location"], "dc1")
        self.assertEqual(snapshot["metadata"]["upstream.step"]["count"], 1)
        mock_logger.info.assert_called_once()

    async def test_file_pretty_text_writes_and_appends(self) -> None:
        run = MagicMock()
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        context = WorkflowContext(
            run_id="run-2",
            workflow_id="wf-2",
            devices={"device-1": device},
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "workflow_steps.show_attributes.executor.settings.data_directory",
                Path(tmp_dir),
            ):
                outcomes = await execute(
                    config={
                        "output_destination": "file",
                        "output_format": "pretty_text",
                        "filename": "dump.txt",
                        "append": False,
                    },
                    context=context,
                    run=run,
                    artifact_service=MagicMock(),
                    node_id="show-attributes-2",
                )

                payload = outcomes[0].context.metadata[
                    f"show-attributes-2{SHOW_ATTRIBUTES_METADATA_SUFFIX}"
                ]
                target = Path(payload["file_path"])
                self.assertTrue(target.exists())
                first_content = target.read_text(encoding="utf-8")
                self.assertIn("=== Workflow Context ===", first_content)
                self.assertIn("lab", first_content)

                await execute(
                    config={
                        "output_destination": "file",
                        "output_format": "pretty_text",
                        "filename": "dump.txt",
                        "append": True,
                    },
                    context=context,
                    run=run,
                    artifact_service=MagicMock(),
                    node_id="show-attributes-2b",
                )
                second_content = target.read_text(encoding="utf-8")
                self.assertIn("---", second_content)
                self.assertGreater(len(second_content), len(first_content))

    async def test_requires_filename_for_file_destination(self) -> None:
        run = MagicMock()
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={})

        with self.assertRaises(ValueError):
            await execute(
                config={
                    "output_destination": "file",
                    "output_format": "json",
                    "filename": "",
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="show-attributes-3",
            )

    def test_build_context_snapshot_is_json_serializable(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"custom": {"site": "a"}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )
        snapshot = build_context_snapshot(context)
        json.dumps(snapshot)
        pretty = format_pretty_text(snapshot)
        self.assertIn("Attribute bags:", pretty)
        self.assertIn("site", pretty)


if __name__ == "__main__":
    unittest.main()
