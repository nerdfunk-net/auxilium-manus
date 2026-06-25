"""Tests for device filename templates."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext
from workflow_steps.common.device_template import (
    TemplateRenderOptions,
    TemplateResolutionError,
    render_device_template,
    render_step_template,
    sanitize_filename,
)


class DeviceTemplateTests(unittest.TestCase):
    def test_render_nautobot_namespace(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={
                "nautobot": {
                    "location": {"name": "DC1"},
                    "custom_fields": {"site_code": "NYC-01"},
                }
            },
        )
        rendered = render_device_template(
            "{device.name}_{nautobot.location.name}_{nautobot.custom_fields.site_code}.cfg",
            device,
            options=TemplateRenderOptions(strict=True, run_id="run-1"),
        )
        self.assertEqual(rendered, "lab_DC1_NYC-01.cfg")

    def test_render_git_namespace(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"git": {"source_file": "inventory/lab.yaml"}},
        )
        rendered = render_device_template(
            "{device.name}_{git.source_file}.cfg",
            device,
            options=TemplateRenderOptions(strict=True),
        )
        self.assertEqual(rendered, "lab_inventory/lab.yaml.cfg")

    def test_legacy_flat_placeholders_resolve_empty(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab.example",
        )
        rendered = render_device_template(
            "{name}_{hostname}.cfg",
            device,
            options=TemplateRenderOptions(strict=False),
        )
        self.assertEqual(rendered, "_.cfg")

    def test_run_namespace_uses_run_id(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        rendered = render_device_template(
            "{device.name}_{run.id}.cfg",
            device,
            options=TemplateRenderOptions(strict=True, run_id="run-uuid-1"),
        )
        self.assertEqual(rendered, "lab_run-uuid-1.cfg")

    def test_strict_fails_when_nautobot_bag_missing(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        with self.assertRaises(TemplateResolutionError) as ctx:
            render_device_template(
                "{nautobot.location.name}.cfg",
                device,
                options=TemplateRenderOptions(strict=True),
            )
        self.assertIn("get-nautobot-attributes", str(ctx.exception))

    def test_strict_fails_when_nautobot_path_empty(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"location": None}},
        )
        with self.assertRaises(TemplateResolutionError) as ctx:
            render_device_template(
                "{nautobot.location.name}.cfg",
                device,
                options=TemplateRenderOptions(strict=True),
            )
        self.assertIn("resolved empty", str(ctx.exception))

    def test_non_strict_allows_empty_nautobot_segment(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        rendered = render_device_template(
            "{device.name}_{nautobot.location.name}.cfg",
            device,
            options=TemplateRenderOptions(strict=False),
        )
        self.assertEqual(rendered, "lab_.cfg")

    def test_render_path_template_with_subdirectories(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"location": {"name": "DC1"}}},
        )
        rendered = render_device_template(
            "./{nautobot.location.name}/{device.name}.cfg",
            device,
            options=TemplateRenderOptions(strict=True, run_id="run-1"),
        )
        self.assertEqual(rendered, "DC1/lab.cfg")

    def test_sanitize_unsafe_chars_in_segment(self) -> None:
        self.assertEqual(sanitize_filename("bad/name<>"), "bad/name_")

    def test_sanitize_relative_path_rejects_parent_segments(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_filename("../etc/passwd")

    def test_render_step_template_supports_timestamp_alias(self) -> None:
        rendered = render_step_template(
            "commit {timestamp} for {run.id}",
            run_id="run-uuid-1",
            workflow_id="wf-1",
        )
        self.assertTrue(rendered.startswith("commit 20"))
        self.assertIn("run-uuid-1", rendered)


if __name__ == "__main__":
    unittest.main()
