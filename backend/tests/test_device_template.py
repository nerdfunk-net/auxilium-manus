"""Tests for device filename templates."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext
from workflow_steps.common.device_template import render_device_template, sanitize_filename


class DeviceTemplateTests(unittest.TestCase):
    def test_render_nested_attribute(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attributes={
                "location": {"name": "DC1"},
                "custom_fields": {"site_code": "NYC-01"},
            },
        )
        rendered = render_device_template(
            "{name}_{attributes.location.name}_{attributes.custom_fields.site_code}.cfg",
            device,
            extra={"timestamp": "20260101-120000"},
        )
        self.assertEqual(rendered, "lab_DC1_NYC-01.cfg")

    def test_sanitize_unsafe_chars(self) -> None:
        self.assertEqual(sanitize_filename("bad/name<>"), "bad_name_")


if __name__ == "__main__":
    unittest.main()
