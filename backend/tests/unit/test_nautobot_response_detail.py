"""Tests for services/nautobot/common/response_detail.py (400 validation detail, C7-03)."""

from __future__ import annotations

import unittest

from services.nautobot.common.response_detail import (
    MAX_DETAIL_CHARS,
    validation_detail,
    validation_fields,
)

_DUPLICATE = (
    "A device named 'device-1' with no tenant already exists in this location: City A. "
    "Device names must be unique when tenant is None and DEVICE_UNIQUENESS='location_tenant_name'."
)


class ValidationDetailTests(unittest.TestCase):
    def test_non_field_error_has_no_prefix(self) -> None:
        self.assertEqual(validation_detail({"__all__": [_DUPLICATE]}), _DUPLICATE)
        self.assertEqual(validation_detail({"non_field_errors": ["bad"]}), "bad")

    def test_field_errors_are_prefixed_with_the_field(self) -> None:
        detail = validation_detail({"name": ["This field is required."], "role": "Invalid pk"})
        self.assertEqual(detail, "name: This field is required.; role: Invalid pk")

    def test_nested_fields_use_a_dotted_path(self) -> None:
        self.assertEqual(
            validation_detail({"custom_fields": {"site": ["Bad value"]}}),
            "custom_fields.site: Bad value",
        )

    def test_list_body_of_strings(self) -> None:
        self.assertEqual(validation_detail(["one", "two"]), "one; two")

    def test_non_structured_bodies_give_none(self) -> None:
        for body in (None, "<html>token=abc</html>", 42, {}, [], {"a": []}, {"a": [1, None]}):
            with self.subTest(body=body):
                self.assertIsNone(validation_detail(body))

    def test_control_characters_and_markup_are_removed(self) -> None:
        detail = validation_detail({"name": ["bad\x00\n<script>alert(1)</script>\tname"]})
        self.assertEqual(detail, "name: bad alert(1) name")

    def test_long_detail_is_capped(self) -> None:
        detail = validation_detail({"name": ["x" * 1000]})
        assert detail is not None
        self.assertLessEqual(len(detail), MAX_DETAIL_CHARS)
        self.assertTrue(detail.endswith("…"))

    def test_only_first_entries_are_used(self) -> None:
        detail = validation_detail({f"f{i}": ["m"] for i in range(20)})
        assert detail is not None
        self.assertEqual(detail.count(";"), 4)


class ValidationFieldsTests(unittest.TestCase):
    def test_top_level_keys_with_messages(self) -> None:
        body = {"asset_tag": ["taken"], "__all__": ["x"], "empty": [], "blank": [" "]}
        self.assertEqual(validation_fields(body), ("asset_tag", "__all__"))

    def test_nested_errors_count_for_the_top_level_key(self) -> None:
        self.assertEqual(
            validation_fields({"custom_fields": {"site": ["bad"]}}), ("custom_fields",)
        )

    def test_list_body_is_a_whole_object_error(self) -> None:
        self.assertEqual(validation_fields(["bad"]), ("__all__",))

    def test_unusable_bodies_give_empty(self) -> None:
        for body in (None, "text", 5, {}, [], {"a": []}):
            with self.subTest(body=body):
                self.assertEqual(validation_fields(body), ())


if __name__ == "__main__":
    unittest.main()
