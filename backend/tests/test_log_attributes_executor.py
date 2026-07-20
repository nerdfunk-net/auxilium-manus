"""Tests for log-attributes executor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.log_attributes.executor import (
    LOG_ATTRIBUTES_METADATA_SUFFIX,
    build_context_snapshot,
    execute,
    format_pretty_text,
)


class LogAttributesExecutorTests(unittest.IsolatedAsyncioTestCase):
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

        with patch("workflow_steps.log_attributes.executor.logger") as mock_logger:
            outcomes = await execute(
                config={
                    "output_destination": "stdout",
                    "output_format": "json",
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="log-attributes-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        payload = outcomes[0].context.metadata[
            f"log-attributes-1{LOG_ATTRIBUTES_METADATA_SUFFIX}"
        ]
        self.assertEqual(payload["output_destination"], "stdout")
        self.assertEqual(payload["device_count"], 1)
        snapshot = payload["snapshot"]
        device_snapshot = snapshot["devices"]["device-1"]
        self.assertEqual(device_snapshot["attribute_bags"]["nautobot"]["role"]["name"], "access-switch")
        self.assertEqual(device_snapshot["attribute_bags"]["git"]["source_file"], "configs/lab.yaml")
        self.assertEqual(device_snapshot["attribute_bags"]["custom"]["location"], "dc1")
        self.assertEqual(snapshot["metadata"]["upstream.step"]["count"], 1)
        mock_logger.info.assert_called()

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
                "workflow_steps.log_attributes.executor.settings.data_directory",
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
                    node_id="log-attributes-2",
                )

                payload = outcomes[0].context.metadata[
                    f"log-attributes-2{LOG_ATTRIBUTES_METADATA_SUFFIX}"
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
                    node_id="log-attributes-2b",
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
                node_id="log-attributes-3",
            )

    async def test_show_parsed_templates_disabled_by_default(self) -> None:
        run = MagicMock()
        artifact_service = InMemoryArtifactService()
        artifact_ref = await artifact_service.store(
            content="hostname lab",
            kind="rendered_template",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "device_config": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": "render-jinja-template-3",
                    "output_key": "device_config",
                    "size_bytes": 12,
                    "kind": "rendered_template",
                }
            },
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"output_destination": "stdout", "output_format": "json"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="log-attributes-4",
        )

        payload = outcomes[0].context.metadata[f"log-attributes-4{LOG_ATTRIBUTES_METADATA_SUFFIX}"]
        self.assertFalse(payload["show_parsed_templates"])
        entry = payload["snapshot"]["devices"]["device-1"]["parsed"]["device_config"]
        self.assertNotIn("rendered_content", entry)

    async def test_show_parsed_templates_resolves_rendered_output(self) -> None:
        run = MagicMock()
        artifact_service = InMemoryArtifactService()
        artifact_ref = await artifact_service.store(
            content="hostname lab\nrole access-switch",
            kind="rendered_template",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            parsed={
                "device_config": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": "render-jinja-template-3",
                    "output_key": "device_config",
                    "size_bytes": 30,
                    "kind": "rendered_template",
                }
            },
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={
                "output_destination": "stdout",
                "output_format": "json",
                "show_parsed_templates": True,
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="log-attributes-5",
        )

        payload = outcomes[0].context.metadata[f"log-attributes-5{LOG_ATTRIBUTES_METADATA_SUFFIX}"]
        self.assertTrue(payload["show_parsed_templates"])
        entry = payload["snapshot"]["devices"]["device-1"]["parsed"]["device_config"]
        self.assertEqual(entry["rendered_content"], "hostname lab\nrole access-switch")

    async def test_show_device_configs_disabled_by_default(self) -> None:
        run = MagicMock()
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content="hostname lab\n!",
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            running_config_ref=running_ref,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"output_destination": "stdout", "output_format": "json"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="log-attributes-6",
        )

        payload = outcomes[0].context.metadata[f"log-attributes-6{LOG_ATTRIBUTES_METADATA_SUFFIX}"]
        self.assertFalse(payload["show_device_configs"])
        device_snapshot = payload["snapshot"]["devices"]["device-1"]
        self.assertNotIn("running_config_content", device_snapshot)
        self.assertNotIn("startup_config_content", device_snapshot)

    async def test_show_device_configs_resolves_running_and_startup(self) -> None:
        run = MagicMock()
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content="hostname lab\ninterface GigabitEthernet0/1\n!",
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        startup_ref = await artifact_service.store(
            content="hostname lab\n!",
            kind="startup_config",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            running_config_ref=running_ref,
            startup_config_ref=startup_ref,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={
                "output_destination": "stdout",
                "output_format": "pretty_text",
                "show_device_configs": True,
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="log-attributes-7",
        )

        payload = outcomes[0].context.metadata[f"log-attributes-7{LOG_ATTRIBUTES_METADATA_SUFFIX}"]
        self.assertTrue(payload["show_device_configs"])
        device_snapshot = payload["snapshot"]["devices"]["device-1"]
        self.assertEqual(
            device_snapshot["running_config_content"],
            "hostname lab\ninterface GigabitEthernet0/1\n!",
        )
        self.assertEqual(device_snapshot["startup_config_content"], "hostname lab\n!")
        self.assertIn("Running config:", payload["content"])
        self.assertIn("interface GigabitEthernet0/1", payload["content"])
        self.assertIn("Startup config:", payload["content"])

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

    def test_build_context_snapshot_redacts_sealed_tacacs_secret(self) -> None:
        from core.crypto import EncryptionService
        from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret

        sealed = seal_secret(
            "s3cr3t", encryption=EncryptionService("test-secret-key-for-log-attributes")
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": sealed}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        snapshot = build_context_snapshot(context)

        leaf = snapshot["devices"]["device-1"]["attribute_bags"]["tacacs"]["shared_secret"]
        self.assertEqual(leaf, REDACTED_PLACEHOLDER)
        pretty = format_pretty_text(snapshot)
        self.assertIn(REDACTED_PLACEHOLDER, pretty)
        self.assertNotIn("s3cr3t", pretty)


if __name__ == "__main__":
    unittest.main()
