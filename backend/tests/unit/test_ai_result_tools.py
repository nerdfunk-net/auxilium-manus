"""query_result / fetch_slice: handle ownership, opt-in, bounds (AI_TOOL_CHAIN.md §6.1)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import (
    InMemoryResultBackend,
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.tools.base import (
    MAX_TOOL_OUTPUT_CHARS,
    Toolbox,
    ToolContext,
    ToolOutput,
)
from services.ai_assistant.tools.envelope import PREVIEW_ROWS
from services.ai_assistant.tools.result_tools import (
    MAX_SLICE_CHARS,
    RESULT_STORE_KEY,
    build_result_tools,
)

ROWS = [
    {
        "Node": f"r{i}",
        "VRF": "default" if i % 2 else "mgmt",
        "Metric": i,
        "Interface": {"hostname": f"r{i}", "name": f"Gi0/{i}"},
        "Tags": ["a", "b"] if i == 3 else [],
    }
    for i in range(60)
]


class _BrokenBackend:
    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ResultStoreUnavailableError("down")

    def get(self, key: str) -> str | None:
        raise ResultStoreUnavailableError("down")


CISCO = (
    "hostname r1\n"
    "enable secret 9 $9$abcdefghijklmnop\n"
    "username admin password 7 0822455D0A16\n"
    "snmp-server community s3cr3tc0mm RO\n"
    "interface Gi0/1\n"
    " key 7 104D000A0618\n"
)
KEY_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"
PEM = f"-----BEGIN PRIVATE KEY-----\n{KEY_BODY}\n{KEY_BODY}\n-----END PRIVATE KEY-----\n"
SECRETS = ("$9$abcdefghijklmnop", "0822455D0A16", "s3cr3tc0mm", "104D000A0618", KEY_BODY)


def _split_text(content: str) -> tuple[dict[str, Any], str]:
    """Header line, then the raw text between <text> tags (as get_artifact does)."""
    header_line, rest = content.split("\n<text>\n", 1)
    body = rest.removesuffix("\n</text>")
    return json.loads(header_line), body


class ResultToolsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = ResultStore(InMemoryResultBackend())
        self.handle = await self.store.put(
            7, StoredResult(kind="routes", data_class=DataClass.INVENTORY, rows=ROWS)
        )
        self.text_handle = await self.store.put(
            7,
            StoredResult(kind="config", data_class=DataClass.CONTENT, text="0123456789" * 1000),
        )
        self.box = self._toolbox(user_id=7, sharing=SharingPolicy(inventory=True, content=True))

    def _toolbox(self, *, user_id: int, sharing: SharingPolicy, store: Any = None) -> Toolbox:
        ctx = ToolContext(
            user_id=user_id,
            redactor=Redactor(),
            extras={RESULT_STORE_KEY: store or self.store},
            sharing=sharing,
        )
        self.ctx = ctx
        return Toolbox(build_result_tools(), ctx)

    async def _call(
        self, name: str, box: Toolbox | None = None, **args: Any
    ) -> tuple[ToolOutput, Any]:
        out = await (box or self.box).execute(ToolCall(id="1", name=name, input=args))
        try:
            return out, json.loads(out.content)
        except ValueError:
            return out, None

    # -- naming / schema ---------------------------------------------------------------------

    def test_tool_names_follow_the_read_rule(self) -> None:
        for tool in build_result_tools():
            self.assertTrue(
                tool.name.startswith(("query_", "fetch_", "get_", "list_", "diff_")), tool.name
            )
            self.assertFalse(tool.name.startswith(("run", "trigger", "execute", "start", "delete")))

    # -- query_result ------------------------------------------------------------------------

    async def test_query_without_filters_returns_a_bounded_envelope(self) -> None:
        out, data = await self._call("query_result", handle=self.handle)

        self.assertFalse(out.is_error)
        self.assertEqual(len(data["rows"]), PREVIEW_ROWS)
        self.assertEqual(data["total_rows"], 60)
        self.assertTrue(data["truncated"])

    async def test_filter_eq_and_limit(self) -> None:
        _, data = await self._call(
            "query_result",
            handle=self.handle,
            filters=[{"field": "VRF", "op": "eq", "value": "mgmt"}],
            limit=5,
        )

        self.assertEqual(data["total_rows"], 30)
        self.assertEqual(len(data["rows"]), 5)
        self.assertTrue(all(r["VRF"] == "mgmt" for r in data["rows"]))

    async def test_filters_are_anded_and_support_numbers_and_nested_paths(self) -> None:
        _, data = await self._call(
            "query_result",
            handle=self.handle,
            filters=[
                {"field": "Metric", "op": "ge", "value": 10},
                {"field": "Metric", "op": "lt", "value": 13},
                {"field": "Interface.name", "op": "startswith", "value": "Gi0/1"},
            ],
        )

        self.assertEqual([r["Metric"] for r in data["rows"]], [10, 11, 12])

    async def test_contains_works_on_strings_and_lists(self) -> None:
        _, by_text = await self._call(
            "query_result",
            handle=self.handle,
            filters=[{"field": "Node", "op": "contains", "value": "r5"}],
        )
        _, by_list = await self._call(
            "query_result",
            handle=self.handle,
            filters=[{"field": "Tags", "op": "contains", "value": "b"}],
        )

        self.assertEqual(by_text["total_rows"], 11)  # r5, r50..r59
        self.assertEqual([r["Node"] for r in by_list["rows"]], ["r3"])

    async def test_fields_projection_supports_dotted_paths(self) -> None:
        _, data = await self._call(
            "query_result", handle=self.handle, fields=["Node", "Interface.name"], limit=2
        )

        self.assertEqual(data["rows"][0], {"Node": "r0", "Interface.name": "Gi0/0"})

    async def test_missing_field_in_a_filter_matches_nothing_without_error(self) -> None:
        out, data = await self._call(
            "query_result",
            handle=self.handle,
            filters=[{"field": "Nope", "op": "eq", "value": "x"}],
        )

        self.assertFalse(out.is_error)
        self.assertEqual(data["total_rows"], 0)

    async def test_invalid_input_goes_back_to_the_model(self) -> None:
        for bad in (
            {"handle": self.handle, "limit": 0},
            {"handle": self.handle, "limit": PREVIEW_ROWS + 1},
            {"handle": self.handle, "unknown": 1},
            {"handle": self.handle, "filters": [{"field": "a", "op": "regex", "value": "x"}]},
            {"handle": self.handle, "filters": [{"field": "a", "op": "eq", "value": "x"}] * 6},
            {"handle": self.handle, "fields": ["f"] * 21},
        ):
            with self.subTest(bad):
                out, _ = await self._call("query_result", **bad)
                self.assertTrue(out.is_error)

    async def test_text_handle_is_refused_by_query_result(self) -> None:
        out, _ = await self._call("query_result", handle=self.text_handle)

        self.assertTrue(out.is_error)
        self.assertIn("fetch_slice", out.content)

    # -- fetch_slice -------------------------------------------------------------------------

    async def test_fetch_slice_pages_rows(self) -> None:
        _, data = await self._call("fetch_slice", handle=self.handle, offset=55, limit=10)

        self.assertEqual([r["Node"] for r in data["rows"]], ["r55", "r56", "r57", "r58", "r59"])
        self.assertEqual(data["total_rows"], 60)
        self.assertFalse(data["truncated"])

    async def test_fetch_slice_rows_limit_is_capped(self) -> None:
        out, _ = await self._call(
            "fetch_slice", handle=self.handle, offset=0, limit=PREVIEW_ROWS + 1
        )

        self.assertTrue(out.is_error)

    async def test_fetch_slice_text_returns_a_bounded_slice_with_position(self) -> None:
        out, _ = await self._call(
            "fetch_slice", handle=self.text_handle, offset=10, limit=MAX_SLICE_CHARS
        )
        header, body = _split_text(out.content)

        self.assertEqual(body, ("0123456789" * 1000)[10 : 10 + MAX_SLICE_CHARS])
        self.assertEqual(header["offset"], 10)
        self.assertEqual(header["next_offset"], 10 + MAX_SLICE_CHARS)
        self.assertEqual(header["total_chars"], 10000)
        self.assertTrue(header["truncated"])

    async def test_fetch_slice_text_last_slice_is_not_truncated(self) -> None:
        out, _ = await self._call("fetch_slice", handle=self.text_handle, offset=9990, limit=100)
        header, body = _split_text(out.content)

        self.assertEqual(len(body), 10)
        self.assertFalse(header["truncated"])
        self.assertIsNone(header["next_offset"])

    async def test_fetch_slice_text_ends_on_a_line_boundary_when_it_can(self) -> None:
        lines = "".join(f"line {i:04d}\n" for i in range(1000))
        handle = await self.store.put(
            7, StoredResult(kind="config", data_class=DataClass.CONTENT, text=lines)
        )

        out, _ = await self._call("fetch_slice", handle=handle, offset=0, limit=1000)
        header, body = _split_text(out.content)

        self.assertTrue(body.endswith("\n") or body.rsplit("\n", 1)[-1].startswith("line "))
        self.assertEqual(lines[: header["next_offset"]].rstrip("\n"), body.rstrip("\n"))

    async def test_fetch_slice_offset_past_the_end_is_empty(self) -> None:
        _, data = await self._call("fetch_slice", handle=self.handle, offset=500, limit=5)

        self.assertEqual(data["rows"], [])

    # -- ownership, opt-in, expiry, outage ---------------------------------------------------

    async def test_other_users_handle_looks_expired(self) -> None:
        box = self._toolbox(user_id=8, sharing=SharingPolicy(inventory=True, content=True))

        for name in ("query_result", "fetch_slice"):
            with self.subTest(name):
                out, _ = await self._call(name, box, handle=self.handle)
                self.assertTrue(out.is_error)
                self.assertIn("expired", out.content)

    async def test_unknown_handle_is_an_error_not_an_exception(self) -> None:
        out, _ = await self._call("query_result", handle="res_000000000000")

        self.assertTrue(out.is_error)

    async def test_opt_out_after_creation_withholds_the_content(self) -> None:
        box = self._toolbox(user_id=7, sharing=SharingPolicy())  # nothing shared

        for name, handle in (("query_result", self.handle), ("fetch_slice", self.text_handle)):
            with self.subTest(name):
                out, data = await self._call(name, box, handle=handle)
                self.assertIn(
                    data["not_shared"], {DataClass.INVENTORY.value, DataClass.CONTENT.value}
                )
                self.assertNotIn("r1", out.content)
                self.assertNotIn("0123", out.content)
                self.assertEqual(out.withheld, (data["not_shared"],))

    async def test_store_outage_is_a_clear_error(self) -> None:
        box = self._toolbox(
            user_id=7, sharing=SharingPolicy(inventory=True), store=ResultStore(_BrokenBackend())
        )

        out, _ = await self._call("query_result", box, handle=self.handle)

        self.assertTrue(out.is_error)
        self.assertIn("unavailable", out.content)

    async def test_missing_store_in_context_is_a_contained_failure(self) -> None:
        ctx = ToolContext(user_id=7, redactor=Redactor(), extras={}, sharing=SharingPolicy())
        out = await Toolbox(build_result_tools(), ctx).execute(
            ToolCall(id="1", name="query_result", input={"handle": self.handle})
        )

        self.assertTrue(out.is_error)

    async def test_audit_refs_record_the_handle_only(self) -> None:
        await self._call("query_result", handle=self.handle)

        self.assertEqual(self.ctx.audit_refs, {f"result:{self.handle}"})

    # -- review findings (doc/analysis/REVIEW.md) ---------------------------------------------

    async def test_text_slice_is_redacted_before_it_is_encoded(self) -> None:
        handle = await self.store.put(
            7, StoredResult(kind="config", data_class=DataClass.CONTENT, text=CISCO)
        )

        out, _ = await self._call("fetch_slice", handle=handle, offset=0, limit=MAX_SLICE_CHARS)

        for secret in SECRETS[:4]:
            self.assertNotIn(secret, out.content)
        self.assertIn("hostname r1", out.content)

    async def test_multiline_table_cells_are_redacted(self) -> None:
        handle = await self.store.put(
            7,
            StoredResult(
                kind="configs",
                data_class=DataClass.CONTENT,
                rows=[{"Node": "r1", "Config": CISCO}],
            ),
        )

        for name in ("query_result", "fetch_slice"):
            with self.subTest(name):
                out, _ = await self._call(name, handle=handle)
                for secret in SECRETS[:4]:
                    self.assertNotIn(secret, out.content)

    async def test_private_key_split_across_slices_is_not_leaked(self) -> None:
        text = ("x" * 3990 + "\n") + PEM + "tail\n"
        handle = await self.store.put(
            7, StoredResult(kind="config", data_class=DataClass.CONTENT, text=text)
        )

        first, _ = await self._call("fetch_slice", handle=handle, offset=0, limit=4010)
        # The model asks for the next part starting inside the key block.
        second, _ = await self._call("fetch_slice", handle=handle, offset=4060, limit=4000)

        self.assertNotIn(KEY_BODY, first.content)
        self.assertNotIn(KEY_BODY, second.content)

    async def test_large_rows_never_produce_cut_json(self) -> None:
        fat = [{"Node": f"r{i}", "Traces": "t" * 3000} for i in range(40)]
        handle = await self.store.put(
            7, StoredResult(kind="trace", data_class=DataClass.INVENTORY, rows=fat)
        )

        out, data = await self._call("query_result", handle=handle)

        self.assertIsNotNone(data, "output must stay valid JSON")
        self.assertLessEqual(len(out.content), MAX_TOOL_OUTPUT_CHARS)
        self.assertTrue(data["truncated"])
        self.assertLess(len(data["rows"]), 20)
        self.assertEqual(data["total_rows"], 40)

    async def test_a_single_row_above_the_limit_is_reported_not_cut(self) -> None:
        huge = [{"Node": "r1", "Traces": "t" * (MAX_TOOL_OUTPUT_CHARS + 100)}]
        handle = await self.store.put(
            7, StoredResult(kind="trace", data_class=DataClass.INVENTORY, rows=huge)
        )

        out, data = await self._call("query_result", handle=handle)

        self.assertIsNotNone(data)
        self.assertEqual(data["rows"], [])
        self.assertIn("fields", data["note"])
        self.assertLessEqual(len(out.content), MAX_TOOL_OUTPUT_CHARS)

    async def test_filtered_matches_can_be_paged_with_offset(self) -> None:
        flt = [{"field": "VRF", "op": "eq", "value": "mgmt"}]  # 30 matches
        _, first = await self._call("query_result", handle=self.handle, filters=flt)
        _, second = await self._call(
            "query_result", handle=self.handle, filters=flt, offset=PREVIEW_ROWS
        )

        self.assertEqual(first["rows"][0]["Node"], "r0")
        self.assertEqual(second["offset"], PREVIEW_ROWS)
        self.assertEqual(second["total_rows"], 30)
        self.assertEqual(len(second["rows"]), 10)
        self.assertTrue(all(r["VRF"] == "mgmt" for r in second["rows"]))
        self.assertFalse({r["Node"] for r in first["rows"]} & {r["Node"] for r in second["rows"]})
        self.assertFalse(second["truncated"])

    async def test_equality_is_not_wider_than_it_says(self) -> None:
        handle = await self.store.put(
            7,
            StoredResult(
                kind="t",
                data_class=DataClass.INVENTORY,
                rows=[
                    {"id": 1, "flag": True, "gone": None, "name": "None", "num": "42"},
                    {"id": 2, "flag": False, "gone": "x", "name": "", "num": 7},
                ],
            ),
        )

        async def count(field: str, op: str, value: Any) -> int:
            _, data = await self._call(
                "query_result",
                handle=handle,
                filters=[{"field": field, "op": op, "value": value}],
            )
            return data["total_rows"]

        self.assertEqual(await count("flag", "eq", 1), 0)  # True is not 1
        self.assertEqual(await count("flag", "eq", True), 1)
        self.assertEqual(await count("gone", "eq", "None"), 0)  # null is not the text "None"
        self.assertEqual(await count("gone", "contains", "No"), 0)
        self.assertEqual(await count("id", "eq", "1"), 1)  # a number may be given as text
        self.assertEqual(await count("num", "gt", 40), 1)  # numeric text compares as a number
        self.assertEqual(await count("num", "lt", "10"), 1)

    async def test_empty_contains_or_startswith_value_is_rejected(self) -> None:
        for op in ("contains", "startswith"):
            with self.subTest(op):
                out, _ = await self._call(
                    "query_result",
                    handle=self.handle,
                    filters=[{"field": "Node", "op": op, "value": ""}],
                )
                self.assertTrue(out.is_error)


if __name__ == "__main__":
    unittest.main()
