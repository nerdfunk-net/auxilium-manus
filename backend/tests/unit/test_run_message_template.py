"""Run-level placeholders are substituted last, so device names are never re-parsed."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext, WorkflowContext
from workflow_steps.common.run_message_template import (
    render_for_all_devices,
    render_for_first_device,
)


def _context(*names: str) -> WorkflowContext:
    devices = {
        f"d{i}": DeviceContext(id=f"d{i}", name=name, hostname=f"host{i}")
        for i, name in enumerate(names)
    }
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


class RunMessageTemplateTests(unittest.TestCase):
    def test_device_name_with_braces_is_not_evaluated(self) -> None:
        context = _context("{device.hostname}", "plain")
        rendered = render_for_all_devices("{devices} ({device_count})", context)
        self.assertEqual(rendered, "{device.hostname}, plain (2)")

    def test_device_name_with_braces_next_to_device_placeholder(self) -> None:
        context = _context("{run.id}")
        rendered = render_for_first_device("{devices}: {device.hostname}", context)
        self.assertEqual(rendered, "{run.id}: host0")

    def test_run_placeholders_still_work(self) -> None:
        context = _context("a", "b")
        self.assertEqual(render_for_all_devices("{device_count}: {devices}", context), "2: a, b")
        self.assertEqual(render_for_all_devices("{device.name}", context), "a\nb")

    def test_markers_in_values_and_names_are_not_expanded(self) -> None:
        marker = "\x00devices\x00"
        device = DeviceContext(
            id="d0",
            name="\x00run_summary\x00",
            hostname="h",
            attribute_bags={"custom": {"note": f"x{marker}y"}},
        )
        context = WorkflowContext(run_id="r", workflow_id="w", devices={"d0": device})
        # a resolved attribute value never expands a run-level marker
        self.assertEqual(render_for_all_devices("{custom.note}", context), "xdevicesy")
        # a device name that holds a marker is printed, not evaluated (single pass)
        rendered = render_for_all_devices("{devices} / {run_summary}", context)
        self.assertTrue(rendered is not None and rendered.startswith("run_summary / 1 device(s)"))


if __name__ == "__main__":
    unittest.main()
