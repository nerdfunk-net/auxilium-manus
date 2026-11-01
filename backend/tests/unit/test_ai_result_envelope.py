"""Tests for the standard tool result envelope (doc/AI_TOOL_CHAIN.md §10a item 2, §15.2)."""

from __future__ import annotations

import json
import unittest

from services.ai_assistant.tools.envelope import (
    PREVIEW_ROWS,
    build_envelope,
    drop_columns,
    envelope_output,
)


def _rows(n: int) -> list[dict[str, int]]:
    return [{"i": i} for i in range(n)]


class BuildEnvelopeTests(unittest.TestCase):
    def test_small_result_is_complete(self) -> None:
        env = build_envelope(_rows(3))

        self.assertEqual(env.rows, _rows(3))
        self.assertEqual(env.total_rows, 3)
        self.assertFalse(env.truncated)
        self.assertTrue(env.total_rows_exact)
        self.assertIsNone(env.handle)

    def test_result_above_preview_size_is_cut_and_flagged(self) -> None:
        env = build_envelope(_rows(PREVIEW_ROWS + 7))

        self.assertEqual(len(env.rows), PREVIEW_ROWS)
        self.assertEqual(env.rows, _rows(PREVIEW_ROWS))
        self.assertEqual(env.total_rows, PREVIEW_ROWS + 7)
        self.assertTrue(env.truncated)
        self.assertTrue(env.total_rows_exact)

    def test_exactly_preview_size_is_not_truncated(self) -> None:
        env = build_envelope(_rows(PREVIEW_ROWS))

        self.assertFalse(env.truncated)

    def test_source_truncation_makes_total_a_lower_bound(self) -> None:
        # The Batfish preview cap hands over limit + 1 rows: more exist, count unknown.
        env = build_envelope(_rows(5), source_truncated=True)

        self.assertTrue(env.truncated)
        self.assertEqual(env.total_rows, 5)
        self.assertFalse(env.total_rows_exact)

    def test_preview_size_is_a_constant_not_a_parameter_but_may_be_lowered(self) -> None:
        env = build_envelope(_rows(10), max_rows=4)

        self.assertEqual(len(env.rows), 4)
        self.assertTrue(env.truncated)

    def test_max_rows_cannot_exceed_the_preview_constant(self) -> None:
        env = build_envelope(_rows(PREVIEW_ROWS + 10), max_rows=PREVIEW_ROWS * 10)

        self.assertEqual(len(env.rows), PREVIEW_ROWS)

    def test_input_is_not_mutated(self) -> None:
        source = _rows(PREVIEW_ROWS + 3)
        before = [dict(r) for r in source]

        env = build_envelope(source)

        self.assertEqual(source, before)
        self.assertIsNot(env.rows, source)

    def test_with_handle_returns_a_new_envelope(self) -> None:
        env = build_envelope(_rows(2))

        with_handle = env.with_handle("res_ab12")

        self.assertIsNone(env.handle)
        self.assertEqual(with_handle.handle, "res_ab12")
        self.assertEqual(with_handle.rows, env.rows)


class EnvelopeOutputTests(unittest.TestCase):
    def test_serialises_the_standard_keys(self) -> None:
        out = envelope_output(build_envelope(_rows(2)))
        data = json.loads(out.content)

        self.assertEqual(data["rows"], _rows(2))
        self.assertEqual(data["total_rows"], 2)
        self.assertIs(data["truncated"], False)
        self.assertNotIn("handle", data)
        self.assertFalse(out.is_error)
        self.assertFalse(out.truncated)

    def test_truncated_envelope_marks_the_tool_output(self) -> None:
        out = envelope_output(build_envelope(_rows(PREVIEW_ROWS + 1)).with_handle("res_1"))
        data = json.loads(out.content)

        self.assertTrue(out.truncated)
        self.assertEqual(data["handle"], "res_1")
        self.assertIs(data["truncated"], True)

    def test_inexact_total_is_reported(self) -> None:
        data = json.loads(envelope_output(build_envelope(_rows(2), source_truncated=True)).content)

        self.assertIs(data["total_rows_exact"], False)

    def test_sets_and_unknown_types_serialise_deterministically(self) -> None:
        rows = [{"tags": {"b", "a"}, "when": object.__new__(_Opaque)}]

        data = json.loads(envelope_output(build_envelope(rows)).content)

        self.assertEqual(data["rows"][0]["tags"], ["a", "b"])
        self.assertEqual(data["rows"][0]["when"], "opaque")

    def test_extra_fields_are_added_beside_the_standard_keys(self) -> None:
        out = envelope_output(build_envelope(_rows(1)), extra={"snapshot": "s1"})

        self.assertEqual(json.loads(out.content)["snapshot"], "s1")

    def test_extra_cannot_overwrite_standard_keys(self) -> None:
        with self.assertRaises(ValueError):
            envelope_output(build_envelope(_rows(1)), extra={"rows": []})


class _Opaque:
    def __str__(self) -> str:
        return "opaque"


class DropColumnsTests(unittest.TestCase):
    def test_removes_named_columns_in_a_copy(self) -> None:
        rows = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]

        out = drop_columns(rows, {"b", "c"})

        self.assertEqual(out, [{"a": 1}, {"a": 3}])
        self.assertEqual(rows[0], {"a": 1, "b": 2})

    def test_empty_drop_set_keeps_everything(self) -> None:
        self.assertEqual(drop_columns(_rows(2), set()), _rows(2))


if __name__ == "__main__":
    unittest.main()
