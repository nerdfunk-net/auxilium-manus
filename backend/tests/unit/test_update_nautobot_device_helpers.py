"""Direct unit tests for the pure helpers extracted from update_nautobot_device/executor.py
in doc/refactoring/FABLE_REST.md Step 4 — see doc/FABLE-ANALYSIS.md §5.2 and §7."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext, WorkflowContext
from workflow_steps.update_nautobot_device.executor import (
    _build_outcomes,
    _count_enabled_fields,
    _parse_config,
    _resolve_device_items,
)


def _context(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices or {})


class ParseConfigTests(unittest.TestCase):
    def test_requires_source_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"update_fields": {"name": {"enabled": True, "value": "x"}}})

    def test_requires_at_least_one_enabled_field_or_interface(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "src-1", "update_fields": {}})

    def test_defaults_are_applied(self) -> None:
        parsed = _parse_config(
            {
                "nautobot_source_id": "src-1",
                "update_fields": {"name": {"enabled": True, "value": "new-name"}},
            }
        )
        self.assertEqual(parsed.source_id, "src-1")
        self.assertTrue(parsed.add_prefix)
        self.assertEqual(parsed.default_prefix_length, "/24")
        self.assertFalse(parsed.sync_interfaces)
        self.assertEqual(parsed.identifier_mode, "from_context")


class ResolveDeviceItemsTests(unittest.TestCase):
    def test_explicit_mode_yields_single_placeholder_item(self) -> None:
        items = _resolve_device_items("explicit", _context())
        self.assertEqual(items, [("explicit", None)])

    def test_from_context_requires_devices(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_device_items("from_context", _context())

    def test_from_context_returns_device_items(self) -> None:
        device = DeviceContext(id="dev-1", name="dev-1", hostname="dev-1")
        items = _resolve_device_items("from_context", _context({"dev-1": device}))
        self.assertEqual(items, [("dev-1", device)])


class CountEnabledFieldsTests(unittest.TestCase):
    def test_counts_top_level_and_custom_fields(self) -> None:
        count = _count_enabled_fields(
            {
                "name": {"enabled": True, "value": "x"},
                "location": {"enabled": False, "value": "y"},
                "custom_fields": {
                    "cf_a": {"enabled": True, "value": "1"},
                    "cf_b": {"enabled": True, "value": "2"},
                },
            }
        )
        self.assertEqual(count, 3)

    def test_zero_when_nothing_enabled(self) -> None:
        count = _count_enabled_fields({"name": {"enabled": False, "value": "x"}})
        self.assertEqual(count, 0)


class BuildOutcomesTests(unittest.TestCase):
    def test_omits_failure_outcome_when_nothing_failed(self) -> None:
        outcomes = _build_outcomes(_context(), success_devices={}, failed_devices={})
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

    def test_includes_failure_outcome_when_something_failed(self) -> None:
        failed_device = DeviceContext(id="dev-1", name="dev-1", hostname="dev-1")
        outcomes = _build_outcomes(
            _context(), success_devices={}, failed_devices={"dev-1": failed_device}
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[1].context.devices["dev-1"].id, "dev-1")


if __name__ == "__main__":
    unittest.main()
