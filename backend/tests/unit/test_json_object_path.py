"""Unit tests for workflow_steps/common/json_object_path.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.json_object_path import get_at_path, set_at_path


class GetAtPathTests(unittest.TestCase):
    def test_plain_dict_traversal(self) -> None:
        self.assertEqual(get_at_path({"a": {"b": "x"}}, "a.b"), "x")

    def test_missing_key_returns_none(self) -> None:
        self.assertIsNone(get_at_path({"a": {"b": "x"}}, "a.c"))
        self.assertIsNone(get_at_path({"a": {"b": "x"}}, "a.b.c"))

    def test_numeric_segment_indexes_a_list(self) -> None:
        doc = {"credentials": [{"username": "noc", "password": "pw"}]}
        self.assertEqual(get_at_path(doc, "credentials.0.password"), "pw")

    def test_numeric_segment_out_of_range_returns_none(self) -> None:
        self.assertIsNone(get_at_path({"a": [1, 2]}, "a.5"))

    def test_numeric_looking_dict_key_is_treated_as_a_key(self) -> None:
        # Cursor is a dict, not a list, so "0" is a literal dict key.
        self.assertEqual(get_at_path({"a": {"0": "x"}}, "a.0"), "x")

    def test_traverse_past_scalar_returns_none(self) -> None:
        self.assertIsNone(get_at_path({"a": "scalar"}, "a.b"))


class SetAtPathTests(unittest.TestCase):
    def test_set_creates_intermediate_dicts(self) -> None:
        result = set_at_path({}, "tacacs.shared_secret", "key123")
        self.assertEqual(result, {"tacacs": {"shared_secret": "key123"}})

    def test_set_overwrites_existing_leaf(self) -> None:
        doc = {"credentials": [{"username": "noc", "password": "old"}]}
        result = set_at_path(doc, "credentials.0.password", "new")
        self.assertEqual(result["credentials"][0]["password"], "new")
        # Sibling key untouched.
        self.assertEqual(result["credentials"][0]["username"], "noc")

    def test_set_does_not_mutate_input(self) -> None:
        doc = {"credentials": [{"password": "old"}]}
        set_at_path(doc, "credentials.0.password", "new")
        self.assertEqual(doc["credentials"][0]["password"], "old")

    def test_set_root_key_preserves_siblings(self) -> None:
        doc = {"credentials": [{"password": "pw"}]}
        result = set_at_path(doc, "tacacs", {"shared_secret": "s3cr3t"})
        self.assertEqual(result["credentials"], doc["credentials"])
        self.assertEqual(result["tacacs"], {"shared_secret": "s3cr3t"})

    def test_set_out_of_range_index_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_at_path({"a": [1, 2]}, "a.5", "x")

    def test_set_into_non_container_scalar_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_at_path({"a": "scalar"}, "a.b", "x")

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_at_path({}, "", "x")
        with self.assertRaises(ValueError):
            get_at_path({}, "   ")


if __name__ == "__main__":
    unittest.main()
