"""render_secret_path: unsafe characters are mapped per segment, never abort a step."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext
from workflow_steps.common.secret_paths import render_secret_path


def _device(name: str) -> DeviceContext:
    return DeviceContext(id="d1", name=name, hostname=name)


def _render(template: str, name: str) -> str:
    return render_secret_path(template, _device(name), strict=False, run_id="r1")


class RenderSecretPathTests(unittest.TestCase):
    def test_unsafe_characters_are_mapped_per_segment(self) -> None:
        for name in ("sw (lab)", "sw#1", "sw,01", "bürgerstr-sw1"):
            path = _render("network/{device.name}/tacacs", name)
            self.assertRegex(path, r"^network/[A-Za-z0-9 _.@=+-]+/tacacs$")

    def test_separators_come_from_the_template_only(self) -> None:
        self.assertEqual(_render("network/{device.name}/tacacs", "a/b"), "network/a_b/tacacs")

    def test_dotdot_and_empty_segments_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _render("network/../{device.name}", "sw1")


if __name__ == "__main__":
    unittest.main()
