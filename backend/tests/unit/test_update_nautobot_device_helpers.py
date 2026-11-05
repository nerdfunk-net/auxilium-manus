"""Direct unit tests for the pure helpers extracted from update_nautobot_device/executor.py
in doc/refactoring/FABLE_REST.md Step 4."""

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
        self.assertEqual(parsed.interfaces_source, "manual")

    def test_invalid_interfaces_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(
                {
                    "nautobot_source_id": "src-1",
                    "update_fields": {"name": {"enabled": True, "value": "x"}},
                    "interfaces_source": "bogus",
                }
            )

    def test_nautobot_origin_with_explicit_identifier_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(
                {
                    "nautobot_source_id": "src-1",
                    "interfaces_source": "nautobot_origin",
                    "device_identifier": {"mode": "explicit", "id": "nb-1"},
                }
            )

    def test_nautobot_origin_satisfies_at_least_one_field_requirement(self) -> None:
        # No enabled update_fields and no manual interfaces — nautobot_origin alone
        # is enough, since per-device bag contents aren't knowable at parse time.
        parsed = _parse_config(
            {
                "nautobot_source_id": "src-1",
                "update_fields": {},
                "interfaces_source": "nautobot_origin",
            }
        )
        self.assertEqual(parsed.interfaces_source, "nautobot_origin")
        self.assertEqual(parsed.manual_interfaces, [])


class ResolveDeviceItemsTests(unittest.TestCase):
    def test_explicit_mode_yields_single_placeholder_item(self) -> None:
        items = _resolve_device_items("explicit", _context())
        self.assertEqual(items, [("explicit", None)])

    def test_from_context_with_no_devices_yields_no_items(self) -> None:
        # The executor turns this into a no-op success; the resolver does not raise.
        self.assertEqual(_resolve_device_items("from_context", _context()), [])

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


class ParsedListConfigTests(unittest.TestCase):
    def _cfg(self, **parsed_list) -> dict:
        return {
            "nautobot_source_id": "src-1",
            "interfaces_source": "parsed_list",
            "parsed_list": parsed_list,
        }

    def test_valid_config_is_parsed_and_counts_as_interfaces(self) -> None:
        parsed = _parse_config(
            self._cfg(
                source_path=" parsed.x.rows ",
                field_map={"name": "interface", "mac_address": " mac ", "mtu": ""},
                fixed_values={"type": "1000base-t", "mode": ""},
            )
        )
        self.assertEqual(parsed.interfaces_source, "parsed_list")
        self.assertEqual(parsed.parsed_list_path, "parsed.x.rows")
        self.assertEqual(parsed.parsed_list_field_map, {"name": "interface", "mac_address": "mac"})
        self.assertEqual(parsed.parsed_list_fixed_values, {"type": "1000base-t"})

    def test_new_interface_type_defaults_to_none(self) -> None:
        parsed = _parse_config(self._cfg(source_path="p", field_map={"name": "i"}))
        self.assertEqual(parsed.parsed_list_new_type_mode, "none")
        self.assertEqual(parsed.parsed_list_new_type_value, "")

    def test_new_interface_type_infer_and_fixed(self) -> None:
        infer = _parse_config(
            self._cfg(
                source_path="p", field_map={"name": "i"}, new_interface_type={"mode": "infer"}
            )
        )
        self.assertEqual(infer.parsed_list_new_type_mode, "infer")
        fixed = _parse_config(
            self._cfg(
                source_path="p",
                field_map={"name": "i"},
                new_interface_type={"mode": "fixed", "value": " Virtual "},
            )
        )
        self.assertEqual(
            (fixed.parsed_list_new_type_mode, fixed.parsed_list_new_type_value),
            ("fixed", "virtual"),
        )

    def test_new_interface_type_fixed_needs_a_value_and_mode_must_be_known(self) -> None:
        for bad in ({"mode": "fixed", "value": " "}, {"mode": "bogus"}, "infer"):
            with self.assertRaises(ValueError):
                _parse_config(
                    self._cfg(source_path="p", field_map={"name": "i"}, new_interface_type=bad)
                )

    def test_source_path_is_required(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(self._cfg(source_path=" ", field_map={"name": "interface"}))

    def test_name_mapping_is_required(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(self._cfg(source_path="parsed.x", field_map={"mtu": "mtu"}))

    def test_explicit_device_identifier_is_refused(self) -> None:
        cfg = self._cfg(source_path="parsed.x", field_map={"name": "interface"})
        cfg["device_identifier"] = {"mode": "explicit", "name": "r1"}
        with self.assertRaises(ValueError):
            _parse_config(cfg)

    def test_sync_interfaces_is_refused_with_a_parsed_list(self) -> None:
        # sync deletes every interface not in the list, before any update runs: an incomplete
        # list (short TextFSM output, a partial path) would delete real interfaces.
        cfg = self._cfg(source_path="parsed.x", field_map={"name": "interface"})
        cfg["sync_interfaces"] = True
        with self.assertRaises(ValueError) as ctx:
            _parse_config(cfg)
        self.assertIn("sync_interfaces", str(ctx.exception))

    def test_manual_interfaces_are_not_validated_when_another_source_is_used(self) -> None:
        for source in ("parsed_list", "nautobot_origin"):
            cfg = self._cfg(source_path="parsed.x", field_map={"name": "interface"})
            cfg["interfaces_source"] = source
            cfg["interfaces"] = "not a list"
            parsed = _parse_config(cfg)
            self.assertEqual(parsed.manual_interfaces, [])

    def test_manual_interfaces_are_still_validated_for_the_manual_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(
                {
                    "nautobot_source_id": "src-1",
                    "interfaces_source": "manual",
                    "interfaces": "not a list",
                }
            )

    def test_unknown_mapped_field_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(
                self._cfg(source_path="parsed.x", field_map={"name": "i", "colour": "c"})
            )



if __name__ == "__main__":
    unittest.main()
