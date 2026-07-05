"""Tests for update-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.update_attribute.executor import execute


def _device(
    device_id: str,
    *,
    name: str | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class UpdateAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_mode_writes_literal_value(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1")},
        )

        outcomes = await execute(
            config={
                "mode": "fixed",
                "destination_path": "custom.location",
                "fixed_value": "office-a",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        self.assertEqual(len(outcomes), 1)
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "custom.location"), "office-a")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

    async def test_regex_mode_skips_when_pattern_does_not_match(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1", name="switchonly.local.zz")},
        )

        outcomes = await execute(
            config={
                "mode": "regex",
                "source_path": "device.name",
                "destination_path": "custom.location",
                "pattern": r"^([^-]+)-",
                "destination_template": r"DC-\1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertIsNone(resolve_device_attribute(updated, "custom.location"))
        self.assertEqual(outcomes[0].context.metadata["node-1.skipped_count"], 1)

    async def test_regex_mode_writes_expanded_value(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1", name="l123-router-1.local.zz")},
        )

        outcomes = await execute(
            config={
                "mode": "regex",
                "source_path": "device.name",
                "destination_path": "custom.location",
                "pattern": r"^([^-]+)-",
                "destination_template": r"DC-\1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "custom.location"), "DC-l123")
        self.assertEqual(outcomes[0].context.metadata["node-1.updated_count"], 1)


if __name__ == "__main__":
    unittest.main()
