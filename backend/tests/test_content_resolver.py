"""Tests for store-artifact content resolution."""

from __future__ import annotations

import unittest

from models.workflow_context import ArtifactRef, DeviceContext, DeviceStatus
from workflow_steps.common.content_resolver import list_exportable_content


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
        parsed={
            "device_config": {
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": "render-jinja-template-3",
                "output_key": "device_config",
                "size_bytes": 24,
                "kind": "rendered_template",
            }
        },
        status=DeviceStatus.OK,
    )


class ContentResolverTests(unittest.TestCase):
    def test_rendered_template_requires_source_step_node_id(self) -> None:
        device = _device_with_rendered_template()
        with self.assertRaises(ValueError) as ctx:
            list_exportable_content(device, content_source="rendered_template")
        self.assertIn("source_step_node_id", str(ctx.exception))

    def test_rendered_template_resolves_matching_step(self) -> None:
        device = _device_with_rendered_template()
        items = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id="render-jinja-template-3",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "rendered_template")
        self.assertEqual(items[0].artifact_ref.artifact_id, "artifact-rendered")
        self.assertEqual(items[0].extra["output_key"], "device_config")

    def test_rendered_template_filters_by_parsed_output_key(self) -> None:
        device = _device_with_rendered_template()
        items = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id="render-jinja-template-3",
            parsed_output_key="device_config",
        )
        self.assertEqual(len(items), 1)

        missing = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id="render-jinja-template-3",
            parsed_output_key="other_key",
        )
        self.assertEqual(missing, [])

    def test_rendered_template_ignores_other_steps(self) -> None:
        device = _device_with_rendered_template()
        items = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id="render-jinja-template-9",
        )
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
