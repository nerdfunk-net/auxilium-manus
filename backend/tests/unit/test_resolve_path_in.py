"""Tests for resolve_path_in, the path resolver for a plain dict/list value."""

from __future__ import annotations

import unittest

from services.workflow_context.attribute_path import resolve_path_in


class ResolvePathInTests(unittest.TestCase):
    DATA = {"a": {"b": 1}, "rows": [{"id": 1, "n": "x"}, {"id": 2, "n": "y"}]}

    def test_dotted_path(self) -> None:
        self.assertEqual(resolve_path_in(self.DATA, "a.b"), 1)

    def test_filter_and_index_segments(self) -> None:
        self.assertEqual(resolve_path_in(self.DATA, "rows[id=2].n"), "y")
        self.assertEqual(resolve_path_in(self.DATA, "rows[0].n"), "x")

    def test_missing_path_is_none(self) -> None:
        self.assertIsNone(resolve_path_in(self.DATA, "a.nope.deeper"))

    def test_non_dict_root_is_none(self) -> None:
        self.assertIsNone(resolve_path_in("text", "a"))
