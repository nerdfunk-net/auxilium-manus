"""diff_results: compare two stored tables by handle (AI_TOOL_CHAIN.md §12.3)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import PREVIEW_ROWS
from services.ai_assistant.tools.result_diff import DiffError, diff_tables
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY, build_result_tools

A = [
    {"Node": "r1", "Network": "10.0.0.0/24", "Next_Hop": "1.1.1.1", "Metric": 10},
    {"Node": "r1", "Network": "10.0.1.0/24", "Next_Hop": "1.1.1.1", "Metric": 10},
    {"Node": "r2", "Network": "10.0.0.0/24", "Next_Hop": "2.2.2.2", "Metric": 20},
]
B = [
    {"Node": "r1", "Network": "10.0.0.0/24", "Next_Hop": "9.9.9.9", "Metric": 11},  # changed
    # r1 10.0.1.0/24 is gone
    {"Node": "r2", "Network": "10.0.0.0/24", "Next_Hop": "2.2.2.2", "Metric": 20},  # same
    {"Node": "r3", "Network": "10.9.0.0/24", "Next_Hop": "3.3.3.3", "Metric": 5},  # new
]
KEY = ["Node", "Network"]


class DiffTablesTests(unittest.TestCase):
    def test_keyed_diff_finds_removed_changed_and_added_rows(self) -> None:
        result = diff_tables(A, B, key=KEY, ignore=frozenset())

        self.assertEqual(result.counts, {"removed": 1, "changed": 1, "added": 1, "unchanged": 1})
        by_change = {r["change"]: r for r in result.rows}
        self.assertEqual(by_change["removed"]["row"]["Network"], "10.0.1.0/24")
        self.assertEqual(by_change["added"]["row"]["Node"], "r3")
        self.assertEqual(by_change["changed"]["key"], {"Node": "r1", "Network": "10.0.0.0/24"})
        self.assertEqual(
            by_change["changed"]["differences"],
            {"Next_Hop": {"a": "1.1.1.1", "b": "9.9.9.9"}, "Metric": {"a": 10, "b": 11}},
        )

    def test_ignored_fields_do_not_count_as_a_change(self) -> None:
        result = diff_tables(A, B, key=KEY, ignore=frozenset({"Next_Hop", "Metric"}))

        self.assertEqual(result.counts["changed"], 0)
        self.assertEqual(result.counts["unchanged"], 2)

    def test_without_a_key_whole_rows_are_compared(self) -> None:
        result = diff_tables(A, B, key=None, ignore=frozenset())

        self.assertEqual(result.counts["changed"], 0)
        self.assertEqual(result.counts["removed"], 2)  # the changed row counts as removed + added
        self.assertEqual(result.counts["added"], 2)
        self.assertEqual(result.counts["unchanged"], 1)

    def test_duplicate_rows_without_a_key_are_counted_not_collapsed(self) -> None:
        row = {"x": 1}

        result = diff_tables([row, row, row], [row], key=None, ignore=frozenset())

        self.assertEqual(result.counts, {"removed": 2, "changed": 0, "added": 0, "unchanged": 1})

    def test_a_key_that_is_not_unique_is_refused(self) -> None:
        with self.assertRaises(DiffError) as ctx:
            diff_tables(A, B, key=["Node"], ignore=frozenset())
        self.assertIn("not unique", str(ctx.exception))

    def test_a_key_column_that_no_row_has_is_refused(self) -> None:
        with self.assertRaises(DiffError) as ctx:
            diff_tables(A, B, key=["Nope"], ignore=frozenset())
        self.assertIn("No row in either table", str(ctx.exception))

    def test_a_row_without_a_key_column_is_refused_not_matched_to_null(self) -> None:
        with_null = [{"Node": "r1", "Network": None, "v": 1}]
        without = [{"Node": "r1", "v": 2}]

        with self.assertRaises(DiffError) as ctx:
            diff_tables(with_null, without, key=KEY, ignore=frozenset())
        self.assertIn("no column 'Network'", str(ctx.exception))

    def test_a_key_whose_value_is_null_is_still_a_key(self) -> None:
        a = [{"Node": "r1", "Network": None, "v": 1}]
        b = [{"Node": "r1", "Network": None, "v": 2}]

        result = diff_tables(a, b, key=KEY, ignore=frozenset())

        self.assertEqual(result.counts["changed"], 1)

    def test_dotted_key_paths_reach_nested_values(self) -> None:
        a = [{"Interface": {"hostname": "r1", "name": "Gi0/1"}, "Active": True}]
        b = [{"Interface": {"hostname": "r1", "name": "Gi0/1"}, "Active": False}]

        result = diff_tables(a, b, key=["Interface.hostname", "Interface.name"], ignore=frozenset())

        self.assertEqual(result.rows[0]["differences"], {"Active": {"a": True, "b": False}})

    def test_identical_tables_have_no_differences(self) -> None:
        result = diff_tables(A, list(A), key=KEY, ignore=frozenset())

        self.assertEqual(result.rows, [])
        self.assertEqual(result.counts["unchanged"], 3)


class DiffResultsToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = ResultStore(InMemoryResultBackend())
        self.a = await self.store.put(
            7, StoredResult(kind="routes", data_class=DataClass.ADDRESSES, rows=A)
        )
        self.b = await self.store.put(
            7, StoredResult(kind="routes", data_class=DataClass.ADDRESSES, rows=B)
        )
        self.box = self._toolbox()

    def _toolbox(self, *, user_id: int = 7, sharing: SharingPolicy | None = None) -> Toolbox:
        ctx = ToolContext(
            user_id=user_id,
            redactor=Redactor(),
            extras={RESULT_STORE_KEY: self.store},
            sharing=sharing or SharingPolicy(inventory=True, addresses=True, content=True),
        )
        self.ctx = ctx
        return Toolbox(build_result_tools(), ctx)

    async def _call(self, box: Toolbox | None = None, **args: Any) -> tuple[ToolOutput, Any]:
        out = await (box or self.box).execute(ToolCall(id="1", name="diff_results", input=args))
        try:
            return out, json.loads(out.content)
        except ValueError:
            return out, None

    async def test_tool_is_registered_and_forbids_unknown_fields(self) -> None:
        tool = {t.name: t for t in build_result_tools()}["diff_results"]

        self.assertIs(tool.input_model.model_config.get("extra"), "forbid")

    async def test_keyed_diff_comes_back_as_an_envelope_with_counts(self) -> None:
        out, data = await self._call(handle_a=self.a, handle_b=self.b, key=KEY)

        self.assertFalse(out.is_error)
        self.assertEqual(data["counts"], {"removed": 1, "changed": 1, "added": 1, "unchanged": 1})
        self.assertEqual({r["change"] for r in data["rows"]}, {"removed", "changed", "added"})
        self.assertEqual(data["total_rows"], 3)

    async def test_a_partial_table_makes_the_diff_say_so(self) -> None:
        full = await self.store.put(
            7, StoredResult(kind="routes", data_class=DataClass.ADDRESSES, rows=A)
        )
        cut = await self.store.put(
            7, StoredResult(kind="routes", data_class=DataClass.ADDRESSES, rows=B, partial=True)
        )

        _, data = await self._call(handle_a=full, handle_b=cut, key=KEY)

        self.assertFalse(data["complete"])
        self.assertFalse(data["total_rows_exact"])
        self.assertIn("prefix", data["note"])
        self.assertIn("past the cut", data["note"])

    async def test_complete_tables_give_a_complete_diff(self) -> None:
        _, data = await self._call(handle_a=self.a, handle_b=self.b, key=KEY)

        self.assertTrue(data["complete"])
        self.assertNotIn("prefix", data.get("note", ""))

    async def test_ignore_fields_reach_the_comparison(self) -> None:
        _, data = await self._call(
            handle_a=self.a, handle_b=self.b, key=KEY, ignore_fields=["Next_Hop", "Metric"]
        )

        self.assertEqual(data["counts"]["changed"], 0)

    async def test_another_users_handle_looks_expired(self) -> None:
        out, _ = await self._call(self._toolbox(user_id=8), handle_a=self.a, handle_b=self.b)

        self.assertTrue(out.is_error)
        self.assertIn("expired", out.content)

    async def test_both_handles_need_their_opt_in(self) -> None:
        content = await self.store.put(
            7, StoredResult(kind="acl", data_class=DataClass.CONTENT, rows=A)
        )
        box = self._toolbox(sharing=SharingPolicy(inventory=True, addresses=True))

        out, data = await self._call(box, handle_a=self.a, handle_b=content)

        self.assertEqual(data["not_shared"], "content_data")
        self.assertEqual(out.withheld, ("content_data",))

    async def test_text_handles_cannot_be_diffed(self) -> None:
        text = await self.store.put(
            7, StoredResult(kind="config", data_class=DataClass.ADDRESSES, text="hostname r1")
        )

        out, _ = await self._call(handle_a=self.a, handle_b=text)

        self.assertTrue(out.is_error)
        self.assertIn("table", out.content)

    async def test_a_bad_key_is_a_clear_tool_error(self) -> None:
        out, _ = await self._call(handle_a=self.a, handle_b=self.b, key=["Node"])

        self.assertTrue(out.is_error)
        self.assertIn("not unique", out.content)

    async def test_a_big_diff_is_previewed_and_stored_with_the_stricter_class(self) -> None:
        many = [{"id": i, "v": i} for i in range(60)]
        changed = [{"id": i, "v": i + 1} for i in range(60)]
        a = await self.store.put(
            7, StoredResult(kind="t", data_class=DataClass.ADDRESSES, rows=many)
        )
        b = await self.store.put(
            7, StoredResult(kind="t", data_class=DataClass.CONTENT, rows=changed)
        )

        _, data = await self._call(handle_a=a, handle_b=b, key=["id"])

        self.assertEqual(len(data["rows"]), PREVIEW_ROWS)
        self.assertEqual(data["total_rows"], 60)
        stored = await self.store.get(7, data["handle"])
        assert stored is not None
        self.assertEqual(stored.data_class, DataClass.CONTENT)
        self.assertEqual(stored.kind, "diff")

    async def test_values_in_the_diff_are_redacted(self) -> None:
        self.ctx.redactor.add_known_secrets(["topsecretvalue1"])
        a = await self.store.put(
            7,
            StoredResult(kind="t", data_class=DataClass.ADDRESSES, rows=[{"id": 1, "v": "old"}]),
        )
        b = await self.store.put(
            7,
            StoredResult(
                kind="t", data_class=DataClass.ADDRESSES, rows=[{"id": 1, "v": "topsecretvalue1"}]
            ),
        )

        out, _ = await self._call(handle_a=a, handle_b=b, key=["id"])

        self.assertNotIn("topsecretvalue1", out.content)
