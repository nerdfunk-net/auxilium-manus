"""Tests for Jinja rendering helpers."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from workflow_steps.common.jinja_render import (
    JinjaTemplateError,
    build_jinja_context,
    render_jinja_template,
    validate_jinja_template,
)


class JinjaRenderTests(unittest.TestCase):
    def test_validate_rejects_empty_template(self) -> None:
        with self.assertRaises(JinjaTemplateError):
            validate_jinja_template("   ")

    def test_render_device_template_with_namespaces(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = build_jinja_context(
            device,
            run_id="run-1",
            workflow_id="wf-1",
        )
        rendered = render_jinja_template(
            "hostname {{ device.hostname }}\nrole {{ nautobot.role.name }}",
            context,
        )
        self.assertIn("hostname lab", rendered)
        self.assertIn("role access-switch", rendered)

    def test_render_fails_on_undefined_variable(self) -> None:
        with self.assertRaises(JinjaTemplateError):
            render_jinja_template("{{ missing.value }}", {"device": {"name": "lab"}})


if __name__ == "__main__":
    unittest.main()
