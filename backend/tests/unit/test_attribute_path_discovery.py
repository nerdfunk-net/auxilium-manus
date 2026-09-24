"""Tests for attribute path discovery (tree building, discriminator inference,
ancestor device merging)."""

from __future__ import annotations

import unittest

from core.models.runs import WorkflowStepResult
from models.workflow_context import DeviceContext, WorkflowContext
from services.workflow_context.attribute_path_discovery import (
    MAX_LIST_ITEM_BRANCHES,
    build_attribute_path_tree,
    infer_discriminator_key,
    merge_ancestor_devices,
)


def _device(device_id: str, **overrides) -> DeviceContext:
    defaults = dict(id=device_id, name=device_id, hostname=device_id)
    defaults.update(overrides)
    return DeviceContext(**defaults)


def _step_result(
    *, id_: int, step_node_id: str, devices: dict[str, DeviceContext], outcome: str = "success"
) -> WorkflowStepResult:
    step = WorkflowStepResult(
        run_id=1,
        step_node_id=step_node_id,
        step_type="noop",
        step_name="Noop",
        status="success",
        output={
            "outcomes": {
                outcome: WorkflowContext(
                    run_id="run-1", workflow_id="wf-1", devices=devices
                ).model_dump(mode="json")
            }
        },
    )
    step.id = id_
    return step


class InferDiscriminatorKeyTests(unittest.TestCase):
    def test_fully_covering_and_distinct_key_is_selected(self) -> None:
        items = [{"address": "10.0.0.1"}, {"address": "10.0.0.2"}]
        key, warning = infer_discriminator_key(items)
        self.assertEqual(key, "address")
        self.assertIsNone(warning)

    def test_prefers_conventional_name_among_fully_qualified_candidates(self) -> None:
        items = [
            {"name": "a", "uuid": "u1"},
            {"name": "b", "uuid": "u2"},
        ]
        key, warning = infer_discriminator_key(items)
        self.assertEqual(key, "name")
        self.assertIsNone(warning)

    def test_alphabetical_tie_break_when_no_conventional_name_qualifies(self) -> None:
        items = [
            {"zeta": "a", "alpha": "x"},
            {"zeta": "b", "alpha": "y"},
        ]
        key, warning = infer_discriminator_key(items)
        self.assertEqual(key, "alpha")
        self.assertIsNone(warning)

    def test_missing_field_on_some_items_is_not_fully_qualified(self) -> None:
        items = [{"address": "10.0.0.1"}, {"other": "x"}]
        key, warning = infer_discriminator_key(items)
        # "address" only covers 1/2 items -> falls back with a warning.
        self.assertEqual(key, "address")
        self.assertIsNotNone(warning)

    def test_duplicate_value_falls_back_with_warning(self) -> None:
        items = [{"address": "10.0.0.1"}, {"address": "10.0.0.1"}]
        key, warning = infer_discriminator_key(items)
        self.assertEqual(key, "address")
        self.assertIsNotNone(warning)
        self.assertIn("address", warning)

    def test_no_scalar_field_returns_none(self) -> None:
        items = [{"nested": {"a": 1}}, {"nested": {"b": 2}}]
        key, warning = infer_discriminator_key(items)
        self.assertIsNone(key)
        self.assertIsNone(warning)

    def test_empty_items_returns_none(self) -> None:
        self.assertEqual(infer_discriminator_key([]), (None, None))


class BuildAttributePathTreeTests(unittest.TestCase):
    def _find(self, nodes, name):
        return next(n for n in nodes if n.name == name)

    def test_device_namespace_has_scalar_children(self) -> None:
        devices = {"d1": _device("d1", network_driver="cisco_ios")}
        tree = build_attribute_path_tree(devices)
        device_node = self._find(tree, "device")
        self.assertEqual(device_node.kind, "dict")
        driver = self._find(device_node.children, "network_driver")
        self.assertEqual(driver.path, "device.network_driver")
        self.assertEqual(driver.kind, "scalar")
        self.assertEqual(driver.example_value, "cisco_ios")

    def test_parsed_namespace_union_across_devices(self) -> None:
        devices = {
            "d1": _device("d1", parsed={"batfish": {"parsed": {"TACACS": {"servers": []}}}}),
            "d2": _device("d2", parsed={"other_key": {"x": 1}}),
        }
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        self.assertEqual(parsed_node.kind, "dict")
        child_names = {c.name for c in parsed_node.children}
        self.assertEqual(child_names, {"batfish", "other_key"})

    def test_raw_config_line_tree_collapses_to_opaque_scalar(self) -> None:
        # Shape produced by get-pyats-running-config: Device.parse("show running-config")
        # keyed by literal CLI lines — must never explode into clickable paths.
        devices = {
            "d1": _device(
                "d1",
                parsed={
                    "pyats_config": {
                        "running": {
                            "hostname LAB": {},
                            "interface Ethernet0/0": {
                                "description xxx": {},
                                "ip address 192.168.178.120 255.255.255.0 secondary": {},
                            },
                            "username noc privilege 15 secret 9 $9$abc": {},
                        }
                    }
                },
            )
        }
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        pyats_node = self._find(parsed_node.children, "pyats_config")
        running_node = self._find(pyats_node.children, "running")
        self.assertEqual(running_node.kind, "scalar")
        self.assertEqual(running_node.children, [])
        self.assertIn("not browsable", running_node.example_value or "")
        # No raw CLI line or secret ever leaks into a node name/path/value.
        self.assertNotIn("secret", running_node.model_dump_json())
        self.assertNotIn("Ethernet0/0", running_node.model_dump_json())

    def test_structured_parsed_config_with_clean_keys_still_browsable(self) -> None:
        # Cisco Config Parser's model also lives under a "running" key, but its
        # own top-level keys are clean field names — must stay fully browsable.
        devices = {
            "d1": _device(
                "d1",
                parsed={
                    "cisco_config": {
                        "running": {
                            "hostname": "LAB",
                            "l3_interfaces": [],
                        }
                    }
                },
            )
        }
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        cisco_node = self._find(parsed_node.children, "cisco_config")
        running_node = self._find(cisco_node.children, "running")
        self.assertEqual(running_node.kind, "dict")
        hostname = self._find(running_node.children, "hostname")
        self.assertEqual(hostname.path, "parsed.cisco_config.running.hostname")
        self.assertEqual(hostname.example_value, "LAB")

    def test_attribute_bag_namespace_present(self) -> None:
        devices = {"d1": _device("d1", attribute_bags={"nautobot": {"role": "access"}})}
        tree = build_attribute_path_tree(devices)
        bag_node = self._find(tree, "nautobot")
        self.assertEqual(bag_node.path, "nautobot")
        role = self._find(bag_node.children, "role")
        self.assertEqual(role.path, "nautobot.role")
        self.assertEqual(role.example_value, "access")

    def test_list_of_dicts_produces_discriminated_filter_segment_children(self) -> None:
        devices = {
            "d1": _device(
                "d1",
                parsed={
                    "batfish_extract_facts": {
                        "parsed": {
                            "TACACS": {
                                "TACACS_Servers": [
                                    {"address": "10.0.0.1", "port": 49},
                                    {"address": "10.0.0.2", "port": 49},
                                ]
                            }
                        }
                    }
                },
            )
        }
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        batfish = self._find(parsed_node.children, "batfish_extract_facts")
        inner_parsed = self._find(batfish.children, "parsed")
        tacacs = self._find(inner_parsed.children, "TACACS")
        servers = self._find(tacacs.children, "TACACS_Servers")

        self.assertEqual(servers.kind, "list")
        self.assertEqual(servers.item_count, 2)
        self.assertIsNone(servers.discriminator_warning)
        child_paths = {c.path for c in servers.children}
        self.assertEqual(
            child_paths,
            {
                "parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers[address=10.0.0.1]",
                "parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers[address=10.0.0.2]",
            },
        )

    def test_list_of_dicts_without_discriminator_is_bare_list_leaf(self) -> None:
        devices = {
            "d1": _device(
                "d1",
                parsed={"acls": {"entries": [{"nested": {"a": 1}}, {"nested": {"b": 2}}]}},
            )
        }
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        acls = self._find(parsed_node.children, "acls")
        entries = self._find(acls.children, "entries")
        self.assertEqual(entries.kind, "list")
        self.assertEqual(entries.children, [])

    def test_list_branches_capped(self) -> None:
        items = [{"address": f"10.0.0.{i}"} for i in range(MAX_LIST_ITEM_BRANCHES + 10)]
        devices = {"d1": _device("d1", parsed={"servers": items})}
        tree = build_attribute_path_tree(devices)
        parsed_node = self._find(tree, "parsed")
        servers = self._find(parsed_node.children, "servers")
        self.assertEqual(servers.item_count, MAX_LIST_ITEM_BRANCHES + 10)
        self.assertLessEqual(len(servers.children), MAX_LIST_ITEM_BRANCHES)


class MergeAncestorDevicesTests(unittest.TestCase):
    def test_only_ancestor_node_ids_are_included(self) -> None:
        step_a = _step_result(id_=1, step_node_id="a", devices={"d1": _device("d1")})
        step_b = _step_result(id_=2, step_node_id="b", devices={"d2": _device("d2")})

        merged, matched = merge_ancestor_devices([step_a, step_b], {"a"})

        self.assertEqual(set(merged), {"d1"})
        self.assertEqual(matched, ["a"])

    def test_later_step_result_overwrites_earlier_for_same_device(self) -> None:
        step_a = _step_result(
            id_=1, step_node_id="a", devices={"d1": _device("d1", parsed={"x": 1})}
        )
        step_b = _step_result(
            id_=2, step_node_id="b", devices={"d1": _device("d1", parsed={"x": 2})}
        )

        merged, _matched = merge_ancestor_devices([step_a, step_b], {"a", "b"})

        self.assertEqual(merged["d1"].parsed["x"], 2)

    def test_malformed_output_is_tolerated(self) -> None:
        step = WorkflowStepResult(
            run_id=1, step_node_id="a", step_type="noop", step_name="Noop", status="failed"
        )
        step.id = 1
        step.output = None

        merged, matched = merge_ancestor_devices([step], {"a"})

        self.assertEqual(merged, {})
        self.assertEqual(matched, [])


if __name__ == "__main__":
    unittest.main()
