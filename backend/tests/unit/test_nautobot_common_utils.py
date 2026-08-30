"""Table-driven tests for services/nautobot/common/utils.py (pure functions)."""

from __future__ import annotations

import unittest

from services.nautobot.common.utils import (
    extract_id_from_url,
    extract_nested_value,
    flatten_nested_fields,
    normalize_tags,
    prepare_update_data,
)

_UUID = "550e8400-e29b-41d4-a716-446655440000"


class FlattenNestedFieldsTests(unittest.TestCase):
    def test_flattens_dotted_keys_to_base(self) -> None:
        self.assertEqual(
            flatten_nested_fields({"platform.name": "ios", "status": "active"}),
            {"platform": "ios", "status": "active"},
        )

    def test_empty_dict(self) -> None:
        self.assertEqual(flatten_nested_fields({}), {})


class ExtractNestedValueTests(unittest.TestCase):
    def test_returns_nested_value(self) -> None:
        self.assertEqual(
            extract_nested_value({"platform": {"name": "ios"}}, "platform.name"), "ios"
        )

    def test_returns_none_when_path_missing(self) -> None:
        self.assertIsNone(extract_nested_value({"platform": {"name": "ios"}}, "platform.version"))

    def test_returns_none_when_intermediate_not_dict(self) -> None:
        self.assertIsNone(extract_nested_value({"platform": "ios"}, "platform.name"))


class NormalizeTagsTests(unittest.TestCase):
    def test_comma_separated_string(self) -> None:
        self.assertEqual(normalize_tags("tag1, tag2 ,tag3"), ["tag1", "tag2", "tag3"])

    def test_list_input_is_stripped_and_filtered(self) -> None:
        self.assertEqual(normalize_tags([" a ", "", "b"]), ["a", "b"])

    def test_single_string(self) -> None:
        self.assertEqual(normalize_tags("single-tag"), ["single-tag"])

    def test_none_and_empty(self) -> None:
        self.assertEqual(normalize_tags(None), [])
        self.assertEqual(normalize_tags(""), [])
        self.assertEqual(normalize_tags("   "), [])

    def test_non_string_scalar_fallback(self) -> None:
        self.assertEqual(normalize_tags(123), ["123"])


class ExtractIdFromUrlTests(unittest.TestCase):
    def test_extracts_uuid(self) -> None:
        self.assertEqual(
            extract_id_from_url(f"/api/dcim/devices/{_UUID}/"), _UUID
        )

    def test_returns_none_without_uuid(self) -> None:
        self.assertIsNone(extract_id_from_url("/api/dcim/devices/"))


class PrepareUpdateDataTests(unittest.TestCase):
    def test_excludes_identifiers_and_empty_values(self) -> None:
        row = {"id": "1", "name": "device1", "status": "active", "serial": ""}
        headers = ["id", "name", "status", "serial"]
        data, iface, ns = prepare_update_data(row, headers)
        self.assertEqual(data, {"status": "active"})
        self.assertIsNone(iface)
        self.assertIsNone(ns)

    def test_tags_field_normalized_to_list(self) -> None:
        row = {"tags": "a,b,c", "status": "active"}
        data, _, _ = prepare_update_data(row, ["tags", "status"])
        self.assertEqual(data["tags"], ["a", "b", "c"])

    def test_nested_field_collapsed_to_base(self) -> None:
        row = {"platform.name": "ios"}
        data, _, _ = prepare_update_data(row, ["platform.name"])
        self.assertEqual(data, {"platform": "ios"})

    def test_interface_config_and_namespace_defaults(self) -> None:
        row = {"interface_name": "", "ip_namespace": ""}
        headers = ["interface_name", "ip_namespace"]
        data, iface, ns = prepare_update_data(row, headers)
        self.assertEqual(iface, {"name": "Loopback", "type": "virtual", "status": "active"})
        self.assertEqual(ns, "Global")
        # interface + namespace fields must not leak into update_data
        self.assertEqual(data, {})

    def test_interface_config_uses_row_values(self) -> None:
        row = {
            "interface_name": "eth0",
            "interface_type": "1000base-t",
            "interface_status": "planned",
        }
        headers = list(row)
        _, iface, _ = prepare_update_data(row, headers)
        self.assertEqual(
            iface, {"name": "eth0", "type": "1000base-t", "status": "planned"}
        )

    def test_custom_excluded_fields_override_defaults(self) -> None:
        row = {"name": "keep-me", "serial": "SN1"}
        data, _, _ = prepare_update_data(row, ["name", "serial"], excluded_fields=["serial"])
        self.assertEqual(data, {"name": "keep-me"})


if __name__ == "__main__":
    unittest.main()
