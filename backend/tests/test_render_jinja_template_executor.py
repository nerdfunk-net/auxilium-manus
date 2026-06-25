"""Tests for render-jinja-template executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import ArtifactRef, Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.render_jinja_template.executor import execute


class RenderJinjaTemplateExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_renders_per_device_and_stores_parsed_output(self) -> None:
        run = MagicMock()
        run.id = 7
        artifact_service = InMemoryArtifactService()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": "hostname {{ device.hostname }}\nrole {{ nautobot.role.name }}",
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="render-jinja-template-1",
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        self.assertIn(Capability.PARSED, success.capabilities)
        entry = success.parsed["device_config"]
        self.assertEqual(entry["output_key"], "device_config")
        self.assertEqual(entry["kind"], "rendered_template")
        content = await artifact_service.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("hostname lab", content)
        self.assertIn("role access-switch", content)

    async def test_marks_device_failed_on_template_error(self) -> None:
        run = MagicMock()
        run.id = 7
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": "{{ missing.value }}",
            },
            context=context,
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="render-jinja-template-2",
        )

        self.assertEqual(len(outcomes), 2)
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "template_error")


if __name__ == "__main__":
    unittest.main()
