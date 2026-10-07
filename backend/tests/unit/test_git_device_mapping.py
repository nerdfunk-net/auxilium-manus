"""Tests for services/git/device_mapping.py."""

from __future__ import annotations

import copy
import unittest

from services.git.device_mapping import (
    CORE_TARGETS,
    DEFAULT_DEVICE_MAPPING,
    NAUTOBOT_TARGETS,
    MappingRule,
    apply_device_mapping,
    collect_available_keys,
    resolve_source_value,
    validate_device_mapping,
)


class ValidateDeviceMappingTests(unittest.TestCase):
    def test_empty_uses_default(self) -> None:
        for raw in (None, [], {}):
            self.assertEqual(validate_device_mapping(raw), list(DEFAULT_DEVICE_MAPPING))

    def test_valid_custom_mapping(self) -> None:
        rules = validate_device_mapping(
            [
                {"source": "device_name", "target": "name"},
                {"source": "site", "target": "location.name"},
            ]
        )
        self.assertEqual(
            rules,
            [MappingRule("device_name", "name"), MappingRule("site", "location.name")],
        )

    def test_strips_whitespace(self) -> None:
        rules = validate_device_mapping([{"source": " dn ", "target": " name "}])
        self.assertEqual(rules, [MappingRule("dn", "name")])

    def test_unknown_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown target"):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "bogus.attr"}]
            )

    def test_uuid_targets_not_mappable(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "id"}]
            )

    def test_duplicate_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "name"}]
            )

    def test_empty_source_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "source"):
            validate_device_mapping([{"source": " ", "target": "name"}])

    def test_missing_name_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            validate_device_mapping([{"source": "site", "target": "location.name"}])

    def test_non_list_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping("name")

    def test_non_dict_row_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping(["name"])


class ResolveSourceValueTests(unittest.TestCase):
    def test_flat_key(self) -> None:
        self.assertEqual(resolve_source_value({"a": 1}, "a"), 1)

    def test_dot_path(self) -> None:
        self.assertEqual(resolve_source_value({"loc": {"site": "X"}}, "loc.site"), "X")

    def test_flat_key_containing_dot_wins(self) -> None:
        self.assertEqual(resolve_source_value({"a.b": 1, "a": {"b": 2}}, "a.b"), 1)

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(resolve_source_value({"a": {}}, "a.b.c"))
        self.assertIsNone(resolve_source_value({"a": "str"}, "a.b"))


class ApplyDeviceMappingTests(unittest.TestCase):
    def test_default_mapping_matches_legacy_shape(self) -> None:
        out = apply_device_mapping(
            {"name": "r1", "primary_ip4": "10.0.0.1/24", "network_driver": "ios"},
            list(DEFAULT_DEVICE_MAPPING),
        )
        self.assertEqual(
            out,
            {
                "name": "r1",
                "primary_ip4": {"address": "10.0.0.1/24"},
                "platform": {"network_driver": "ios"},
            },
        )

    def test_custom_mapping_builds_nested_shape(self) -> None:
        rules = [
            MappingRule("device_name", "name"),
            MappingRule("site", "location.name"),
            MappingRule("parent_site", "location.parent.name"),
            MappingRule("state", "status.name"),
            MappingRule("pos", "position"),
        ]
        out = apply_device_mapping(
            {
                "device_name": "r1",
                "site": "City A",
                "parent_site": "State A",
                "state": "Active",
                "pos": 3,
            },
            rules,
        )
        self.assertEqual(out["name"], "r1")
        self.assertEqual(out["location"], {"name": "City A", "parent": {"name": "State A"}})
        self.assertEqual(out["status"], {"name": "Active"})
        self.assertEqual(out["position"], "3")

    def test_dot_path_source(self) -> None:
        out = apply_device_mapping({"meta": {"n": "r1"}}, [MappingRule("meta.n", "name")])
        self.assertEqual(out, {"name": "r1"})

    def test_missing_name_returns_none(self) -> None:
        self.assertIsNone(apply_device_mapping({"site": "X"}, [MappingRule("n", "name")]))

    def test_non_dict_entry_returns_none(self) -> None:
        self.assertIsNone(apply_device_mapping("nope", list(DEFAULT_DEVICE_MAPPING)))

    def test_empty_and_none_values_skipped(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "s": "", "x": None},
            [MappingRule("n", "name"), MappingRule("s", "serial"), MappingRule("x", "role.name")],
        )
        self.assertEqual(out, {"name": "r1"})

    def test_structured_values_skipped(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "s": ["a"]}, [MappingRule("n", "name"), MappingRule("s", "serial")]
        )
        self.assertEqual(out, {"name": "r1"})

    def test_input_not_mutated(self) -> None:
        entry = {"n": "r1", "loc": {"site": "X"}}
        snapshot = copy.deepcopy(entry)
        apply_device_mapping(
            entry, [MappingRule("n", "name"), MappingRule("loc.site", "location.name")]
        )
        self.assertEqual(entry, snapshot)


class CollectAvailableKeysTests(unittest.TestCase):
    def test_top_level_and_dotted_leaf_keys(self) -> None:
        keys = collect_available_keys(
            [{"name": "a", "loc": {"site": "x", "deep": {"k": 1}}}, {"name": "b", "extra": 1}]
        )
        self.assertEqual(keys, ["extra", "loc", "loc.deep", "loc.deep.k", "loc.site", "name"])

    def test_empty(self) -> None:
        self.assertEqual(collect_available_keys([]), [])


class CatalogTests(unittest.TestCase):
    def test_core_targets_subset_of_catalog(self) -> None:
        self.assertLessEqual(set(CORE_TARGETS), set(NAUTOBOT_TARGETS))

    def test_no_uuid_targets(self) -> None:
        self.assertFalse([t for t in NAUTOBOT_TARGETS if t == "id" or t.endswith(".id")])

    def test_default_mapping_targets_in_catalog(self) -> None:
        self.assertLessEqual({r.target for r in DEFAULT_DEVICE_MAPPING}, set(NAUTOBOT_TARGETS))


if __name__ == "__main__":
    unittest.main()
