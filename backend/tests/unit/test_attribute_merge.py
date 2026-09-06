"""Tests for workflow_steps.common.attribute_merge."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from workflow_steps.common.attribute_merge import (
    deep_merge_mapping,
    merge_into_device_attribute,
    validate_merge_destination,
)


def _device(*, bags: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags=bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class DeepMergeMappingTests(unittest.TestCase):
    def test_adds_new_keys(self) -> None:
        self.assertEqual(
            deep_merge_mapping({"a": 1}, {"b": 2}, overwrite=False), {"a": 1, "b": 2}
        )

    def test_overwrite_false_keeps_existing_leaf(self) -> None:
        self.assertEqual(
            deep_merge_mapping({"a": "old"}, {"a": "new", "b": 2}, overwrite=False),
            {"a": "old", "b": 2},
        )

    def test_overwrite_true_replaces_leaf(self) -> None:
        self.assertEqual(
            deep_merge_mapping({"a": "old"}, {"a": "new"}, overwrite=True), {"a": "new"}
        )

    def test_recurses_into_nested_dicts(self) -> None:
        result = deep_merge_mapping(
            {"net": {"mtu": 1500, "vlan": 10}},
            {"net": {"vlan": 20, "mode": "trunk"}},
            overwrite=True,
        )
        self.assertEqual(result, {"net": {"mtu": 1500, "vlan": 20, "mode": "trunk"}})

    def test_list_replaced_not_concatenated(self) -> None:
        self.assertEqual(
            deep_merge_mapping({"x": [1, 2, 3]}, {"x": [9]}, overwrite=True), {"x": [9]}
        )
        self.assertEqual(
            deep_merge_mapping({"x": [1, 2, 3]}, {"x": [9]}, overwrite=False), {"x": [1, 2, 3]}
        )

    def test_type_conflict_dict_vs_scalar(self) -> None:
        self.assertEqual(
            deep_merge_mapping({"a": {"x": 1}}, {"a": "s"}, overwrite=True), {"a": "s"}
        )
        self.assertEqual(
            deep_merge_mapping({"a": {"x": 1}}, {"a": "s"}, overwrite=False), {"a": {"x": 1}}
        )

    def test_does_not_mutate_arguments(self) -> None:
        base = {"a": 1, "n": {"x": 1}}
        incoming = {"n": {"y": 2}}
        result = deep_merge_mapping(base, incoming, overwrite=True)
        self.assertEqual(base, {"a": 1, "n": {"x": 1}})
        self.assertEqual(incoming, {"n": {"y": 2}})
        result["n"]["z"] = 3
        self.assertEqual(base["n"], {"x": 1})

    def test_empty_incoming_returns_copy(self) -> None:
        base = {"a": 1}
        result = deep_merge_mapping(base, {}, overwrite=True)
        self.assertEqual(result, {"a": 1})
        self.assertIsNot(result, base)


class ValidateMergeDestinationTests(unittest.TestCase):
    def test_splits_bare_bag(self) -> None:
        self.assertEqual(validate_merge_destination("data"), ("data", ""))

    def test_splits_bag_dot_field(self) -> None:
        self.assertEqual(validate_merge_destination("data.site.region"), ("data", "site.region"))

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_merge_destination("   ")

    def test_rejects_device_prefix(self) -> None:
        with self.assertRaises(ValueError):
            validate_merge_destination("device.name")

    def test_rejects_device_scalar(self) -> None:
        with self.assertRaises(ValueError):
            validate_merge_destination("name")

    def test_rejects_reserved_namespaces(self) -> None:
        for path in ("parsed.foo", "run_input.bar"):
            with self.assertRaises(ValueError):
                validate_merge_destination(path)


class MergeIntoDeviceAttributeTests(unittest.TestCase):
    def test_merges_into_bag_root(self) -> None:
        device = _device(bags={"data": {"a": "old", "keep": 1}})
        updated = merge_into_device_attribute(
            device, "data", {"a": "new", "b": 2}, overwrite=False
        )
        self.assertEqual(updated.attribute_bags["data"], {"a": "old", "keep": 1, "b": 2})
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

    def test_merges_into_nested_subpath(self) -> None:
        device = _device()
        updated = merge_into_device_attribute(
            device, "data.site", {"region": "emea"}, overwrite=True
        )
        self.assertEqual(updated.attribute_bags["data"], {"site": {"region": "emea"}})

    def test_result_bags_not_shared_with_source(self) -> None:
        original = {"data": {"a": 1}}
        device = _device(bags=original)
        updated = merge_into_device_attribute(device, "data", {"b": 2}, overwrite=True)
        updated.attribute_bags["data"]["c"] = 3
        self.assertEqual(device.attribute_bags["data"], {"a": 1})
        self.assertEqual(original["data"], {"a": 1})

    def test_subpath_merges_into_existing_mapping(self) -> None:
        device = _device(bags={"data": {"site": {"region": "old", "tz": "utc"}}})
        updated = merge_into_device_attribute(
            device, "data.site", {"region": "emea"}, overwrite=True
        )
        self.assertEqual(
            updated.attribute_bags["data"]["site"], {"region": "emea", "tz": "utc"}
        )

    def test_subpath_over_existing_scalar_respects_overwrite(self) -> None:
        device = _device(bags={"data": {"site": "keep-me"}})
        skipped = merge_into_device_attribute(
            device, "data.site", {"region": "emea"}, overwrite=False
        )
        self.assertEqual(skipped.attribute_bags["data"]["site"], "keep-me")
        replaced = merge_into_device_attribute(
            device, "data.site", {"region": "emea"}, overwrite=True
        )
        self.assertEqual(replaced.attribute_bags["data"]["site"], {"region": "emea"})

    def test_rejected_destination_raises(self) -> None:
        with self.assertRaises(ValueError):
            merge_into_device_attribute(_device(), "parsed.x", {"a": 1}, overwrite=True)


if __name__ == "__main__":
    unittest.main()
