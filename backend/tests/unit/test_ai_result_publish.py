"""publish_table: preview + handle + redaction for table-returning tools (AI_TOOL_CHAIN.md §6.1)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import (
    InMemoryResultBackend,
    ResultStore,
    ResultStoreUnavailableError,
)
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.envelope import PREVIEW_ROWS, build_envelope, envelope_output
from services.ai_assistant.tools.result_publish import publish_table
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"i": i, "pad": "x"} for i in range(n)]


def _ctx(store: ResultStore | None, user_id: int = 7) -> ToolContext:
    extras = {RESULT_STORE_KEY: store} if store is not None else {}
    return ToolContext(
        user_id=user_id, redactor=Redactor(), extras=extras, sharing=SharingPolicy(addresses=True)
    )


class _Broken:
    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ResultStoreUnavailableError("down")

    def get(self, key: str) -> str | None:
        raise ResultStoreUnavailableError("down")


class PublishTableTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_result_has_no_handle_and_is_not_stored(self) -> None:
        backend = InMemoryResultBackend()
        out = await publish_table(
            _ctx(ResultStore(backend)), _rows(3), kind="routes", data_class=DataClass.ADDRESSES
        )
        data = json.loads(out.content)

        self.assertEqual(data["total_rows"], 3)
        self.assertNotIn("handle", data)
        self.assertFalse(out.truncated)
        self.assertEqual(backend._data, {})

    async def test_big_result_is_stored_and_the_handle_returns_all_rows(self) -> None:
        store = ResultStore(InMemoryResultBackend())
        ctx = _ctx(store)

        out = await publish_table(ctx, _rows(60), kind="routes", data_class=DataClass.ADDRESSES)
        data = json.loads(out.content)

        self.assertEqual(len(data["rows"]), PREVIEW_ROWS)
        self.assertEqual(data["total_rows"], 60)
        self.assertTrue(data["truncated"])
        stored = await store.get(7, data["handle"])
        assert stored is not None
        self.assertEqual(stored.rows, _rows(60))
        self.assertEqual(stored.data_class, DataClass.ADDRESSES)
        self.assertEqual(stored.kind, "routes")

    async def test_source_truncation_is_reported_as_a_lower_bound(self) -> None:
        out = await publish_table(
            _ctx(ResultStore(InMemoryResultBackend())),
            _rows(60),
            kind="routes",
            data_class=DataClass.ADDRESSES,
            source_truncated=True,
        )

        self.assertFalse(json.loads(out.content)["total_rows_exact"])

    async def test_missing_store_degrades_to_a_preview_with_a_note(self) -> None:
        out = await publish_table(_ctx(None), _rows(60), kind="r", data_class=DataClass.ADDRESSES)
        data = json.loads(out.content)

        self.assertNotIn("handle", data)
        self.assertEqual(len(data["rows"]), PREVIEW_ROWS)
        self.assertIn("could not be stored", data["note"])

    async def test_store_outage_degrades_the_same_way(self) -> None:
        out = await publish_table(
            _ctx(ResultStore(_Broken())), _rows(60), kind="r", data_class=DataClass.ADDRESSES
        )
        data = json.loads(out.content)

        self.assertNotIn("handle", data)
        self.assertIn("could not be stored", data["note"])
        self.assertFalse(out.is_error)

    async def test_oversized_table_is_stored_partially_and_says_so(self) -> None:
        store = ResultStore(InMemoryResultBackend())
        big = [{"i": i, "pad": "x" * 2000} for i in range(1500)]  # about 3 MB

        out = await publish_table(_ctx(store), big, kind="r", data_class=DataClass.ADDRESSES)
        data = json.loads(out.content)

        stored = await store.get(7, data["handle"])
        assert stored is not None and stored.rows is not None
        self.assertLess(len(stored.rows), 1500)
        self.assertEqual(stored.rows, big[: len(stored.rows)])
        self.assertIn(str(len(stored.rows)), data["note"])
        self.assertEqual(data["total_rows"], 1500)

    async def test_preview_rows_are_redacted_as_data(self) -> None:
        cfg = "enable secret 9 $9$abcdefghijklmnop\nhostname r1\n"
        out = await publish_table(
            _ctx(ResultStore(InMemoryResultBackend())),
            [{"Node": "r1", "Config": cfg}],
            kind="c",
            data_class=DataClass.CONTENT,
        )

        self.assertNotIn("$9$abcdefghijklmnop", out.content)

    async def test_extra_fields_are_added(self) -> None:
        out = await publish_table(
            _ctx(None), _rows(2), kind="r", data_class=DataClass.ADDRESSES, extra={"snapshot": "s1"}
        )

        self.assertEqual(json.loads(out.content)["snapshot"], "s1")


class EnvelopeNoteTests(unittest.TestCase):
    def test_note_is_part_of_the_output(self) -> None:
        env = build_envelope(_rows(1)).with_note("hello")

        self.assertEqual(json.loads(envelope_output(env).content)["note"], "hello")

    def test_shrink_note_is_appended_to_an_existing_note(self) -> None:
        fat = [{"t": "x" * 3000} for _ in range(20)]
        env = build_envelope(fat).with_note("earlier")

        note = json.loads(envelope_output(env).content)["note"]

        self.assertTrue(note.startswith("earlier"))
        self.assertIn("fit the output limit", note)


if __name__ == "__main__":
    unittest.main()
