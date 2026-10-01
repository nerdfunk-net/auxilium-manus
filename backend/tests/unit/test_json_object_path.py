"""Unit tests for workflow_steps/common/json_object_path.py."""

from __future__ import annotations

import unittest

from workflow_steps.common.json_object_path import get_at_path, set_at_path, top_level_key


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


_TACACS_DOC = {
    "tacacs": [
        {"address": "1.2.3.4", "key": "mykey", "level": 7, "server": "tacacs-server"},
        {"address": "5.6.7.8", "key": "other", "level": 7, "server": "backup"},
    ]
}


class FilterSegmentTests(unittest.TestCase):
    """``key[field=value]`` selects the first list item whose field matches."""

    def test_set_updates_the_matching_item_only(self) -> None:
        result = set_at_path(_TACACS_DOC, "tacacs[address=1.2.3.4].key", "new")
        self.assertEqual(result["tacacs"][0]["key"], "new")
        self.assertEqual(result["tacacs"][0]["server"], "tacacs-server")
        self.assertEqual(result["tacacs"][1], _TACACS_DOC["tacacs"][1])

    def test_value_may_contain_dots(self) -> None:
        # The filter value is an IP address; it must not be split on ".".
        result = set_at_path(_TACACS_DOC, "tacacs[address=5.6.7.8].key", "new")
        self.assertEqual(result["tacacs"][1]["key"], "new")
        self.assertEqual(result["tacacs"][0]["key"], "mykey")

    def test_filter_on_the_field_being_changed(self) -> None:
        # The exact path from the bug report, relative to the local context.
        result = set_at_path(_TACACS_DOC, "tacacs[key=mykey].key", "new")
        self.assertEqual(result["tacacs"][0]["key"], "new")

    def test_set_does_not_mutate_input(self) -> None:
        set_at_path(_TACACS_DOC, "tacacs[address=1.2.3.4].key", "new")
        self.assertEqual(_TACACS_DOC["tacacs"][0]["key"], "mykey")

    def test_filter_as_the_last_segment_replaces_the_item(self) -> None:
        item = {"address": "1.2.3.4", "key": "k", "level": 15, "server": "s"}
        result = set_at_path(_TACACS_DOC, "tacacs[address=1.2.3.4]", item)
        self.assertEqual(result["tacacs"][0], item)
        self.assertEqual(len(result["tacacs"]), 2)

    def test_first_match_wins_when_several_items_match(self) -> None:
        result = set_at_path(_TACACS_DOC, "tacacs[level=7].key", "new")
        self.assertEqual(result["tacacs"][0]["key"], "new")
        self.assertEqual(result["tacacs"][1]["key"], "other")

    def test_no_match_raises_and_never_extends_the_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "no item"):
            set_at_path(_TACACS_DOC, "tacacs[address=9.9.9.9].key", "new")

    def test_missing_or_non_list_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_at_path({}, "tacacs[address=1.2.3.4].key", "new")
        with self.assertRaises(ValueError):
            set_at_path({"tacacs": {"address": "1.2.3.4"}}, "tacacs[address=1.2.3.4].key", "x")

    def test_get_returns_value_at_filtered_item(self) -> None:
        self.assertEqual(get_at_path(_TACACS_DOC, "tacacs[address=5.6.7.8].key"), "other")

    def test_get_returns_none_without_a_match(self) -> None:
        self.assertIsNone(get_at_path(_TACACS_DOC, "tacacs[address=9.9.9.9].key"))
        self.assertIsNone(get_at_path({}, "tacacs[address=1.2.3.4].key"))

    def test_filter_matches_by_string_equality_on_scalars(self) -> None:
        self.assertEqual(get_at_path(_TACACS_DOC, "tacacs[level=7].server"), "tacacs-server")

    def test_dotted_field_resolves_inside_each_item(self) -> None:
        doc = {"servers": [{"endpoint": {"ip": "10.0.0.5"}, "key": "a"}]}
        self.assertEqual(get_at_path(doc, "servers[endpoint.ip=10.0.0.5].key"), "a")

    def test_filter_on_a_nested_container_never_matches(self) -> None:
        doc = {"servers": [{"endpoint": {"ip": "10.0.0.5"}, "key": "a"}]}
        self.assertIsNone(get_at_path(doc, "servers[endpoint=10.0.0.5].key"))


class IndexSegmentTests(unittest.TestCase):
    """``key[N]`` is the index form attribute paths use; it must work here too."""

    _DOC = {
        "credentials": [
            {"username": "a", "password": "p0"},
            {"username": "b", "password": "p1"},
        ]
    }

    def test_get_by_bracket_index(self) -> None:
        self.assertEqual(get_at_path(self._DOC, "credentials[1].password"), "p1")

    def test_set_by_bracket_index_keeps_siblings_and_input(self) -> None:
        result = set_at_path(self._DOC, "credentials[0].password", "new")
        self.assertEqual(result["credentials"][0], {"username": "a", "password": "new"})
        self.assertEqual(result["credentials"][1]["password"], "p1")
        self.assertEqual(self._DOC["credentials"][0]["password"], "p0")

    def test_bracket_index_as_last_segment_replaces_the_item(self) -> None:
        result = set_at_path(self._DOC, "credentials[1]", {"username": "c"})
        self.assertEqual(result["credentials"][1], {"username": "c"})

    def test_out_of_range_raises_on_write_and_is_none_on_read(self) -> None:
        with self.assertRaisesRegex(ValueError, "out of range"):
            set_at_path(self._DOC, "credentials[5].password", "x")
        self.assertIsNone(get_at_path(self._DOC, "credentials[5].password"))

    def test_non_list_raises_on_write(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a list"):
            set_at_path({"credentials": {"a": 1}}, "credentials[0].password", "x")

    def test_dot_index_form_still_works(self) -> None:
        self.assertEqual(get_at_path(self._DOC, "credentials.0.password"), "p0")

    def test_top_level_key_strips_the_index(self) -> None:
        self.assertEqual(top_level_key("credentials[0].password"), "credentials")


class TopLevelKeyTests(unittest.TestCase):
    def test_plain_and_dotted_paths(self) -> None:
        self.assertEqual(top_level_key("tacacs"), "tacacs")
        self.assertEqual(top_level_key("credentials.0.password"), "credentials")

    def test_filter_segment_is_stripped(self) -> None:
        self.assertEqual(top_level_key("tacacs[address=1.2.3.4].key"), "tacacs")

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            top_level_key("  ")


if __name__ == "__main__":
    unittest.main()
