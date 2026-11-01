"""Tests for the short-lived result handle store (doc/AI_TOOL_CHAIN.md §6.1, D6)."""

from __future__ import annotations

import json
import unittest

import fakeredis
import redis

from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.results.store import (
    HANDLE_PATTERN,
    MAX_STORED_BYTES,
    InMemoryResultBackend,
    RedisResultBackend,
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)


def _result(**overrides) -> StoredResult:
    base = {"kind": "routes", "data_class": DataClass.INVENTORY, "rows": [{"a": 1}, {"a": 2}]}
    base.update(overrides)
    return StoredResult(**base)


def _backends():
    return {
        "memory": lambda: InMemoryResultBackend(),
        "redis": lambda: RedisResultBackend(fakeredis.FakeRedis(decode_responses=True)),
    }


class ResultStoreContractTests(unittest.IsolatedAsyncioTestCase):
    """The same behaviour for every backend."""

    async def test_put_then_get_round_trips(self) -> None:
        for name, make in _backends().items():
            with self.subTest(name):
                store = ResultStore(make())
                handle = await store.put(7, _result())

                self.assertRegex(handle, HANDLE_PATTERN)
                got = await store.get(7, handle)
                self.assertEqual(got, _result())

    async def test_text_results_round_trip(self) -> None:
        for name, make in _backends().items():
            with self.subTest(name):
                store = ResultStore(make())
                handle = await store.put(7, _result(kind="config", rows=None, text="line1\nline2"))

                got = await store.get(7, handle)

                assert got is not None
                self.assertEqual(got.text, "line1\nline2")
                self.assertIsNone(got.rows)

    async def test_other_user_cannot_read_a_handle(self) -> None:
        for name, make in _backends().items():
            with self.subTest(name):
                store = ResultStore(make())
                handle = await store.put(7, _result())

                self.assertIsNone(await store.get(8, handle))

    async def test_unknown_and_malformed_handles_return_none(self) -> None:
        store = ResultStore(InMemoryResultBackend())

        self.assertIsNone(await store.get(7, "res_000000000000"))
        for bad in ("", "x", "res_", "../etc", "res_ZZZZZZZZZZZZ", "res_" + "a" * 200):
            with self.subTest(bad):
                self.assertIsNone(await store.get(7, bad))

    async def test_handles_are_unique(self) -> None:
        store = ResultStore(InMemoryResultBackend())

        handles = {await store.put(7, _result()) for _ in range(50)}

        self.assertEqual(len(handles), 50)

    async def test_oversized_result_is_rejected(self) -> None:
        store = ResultStore(InMemoryResultBackend())
        big = _result(rows=None, text="x" * (MAX_STORED_BYTES + 1))

        with self.assertRaises(ValueError):
            await store.put(7, big)

    async def test_result_needs_rows_or_text(self) -> None:
        with self.assertRaises(ValueError):
            _result(rows=None, text=None)
        with self.assertRaises(ValueError):
            _result(rows=[], text="x")

    async def test_non_json_values_are_stored_as_text(self) -> None:
        store = ResultStore(InMemoryResultBackend())
        handle = await store.put(7, _result(rows=[{"tags": {"b", "a"}}]))

        got = await store.get(7, handle)

        assert got is not None and got.rows is not None
        self.assertEqual(got.rows[0]["tags"], ["a", "b"])


class RedisBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_entry_gets_a_ttl_and_expires(self) -> None:
        client = fakeredis.FakeRedis(decode_responses=True)
        store = ResultStore(RedisResultBackend(client), ttl_seconds=60)
        handle = await store.put(7, _result())

        keys = client.keys("*")
        self.assertEqual(len(keys), 1)
        self.assertTrue(0 < client.ttl(keys[0]) <= 60)

        client.delete(keys[0])  # what expiry does
        self.assertIsNone(await store.get(7, handle))

    async def test_key_contains_the_user_id(self) -> None:
        client = fakeredis.FakeRedis(decode_responses=True)
        store = ResultStore(RedisResultBackend(client))
        await store.put(42, _result())

        self.assertIn(":42:", client.keys("*")[0])

    async def test_unavailable_redis_raises_a_typed_error_on_put_and_get(self) -> None:
        class Broken:
            def set(self, *a, **k):
                raise redis.ConnectionError("down")

            def get(self, *a, **k):
                raise redis.ConnectionError("down")

        store = ResultStore(RedisResultBackend(Broken()))  # type: ignore[arg-type]

        with self.assertRaises(ResultStoreUnavailableError):
            await store.put(7, _result())
        with self.assertRaises(ResultStoreUnavailableError):
            await store.get(7, "res_" + "a" * 12)

    async def test_corrupt_entry_is_treated_as_missing(self) -> None:
        client = fakeredis.FakeRedis(decode_responses=True)
        store = ResultStore(RedisResultBackend(client))
        handle = await store.put(7, _result())
        client.set(client.keys("*")[0], "not json{")

        self.assertIsNone(await store.get(7, handle))


if __name__ == "__main__":
    unittest.main()


class PartialFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_partial_flag_round_trips(self) -> None:
        store = ResultStore(InMemoryResultBackend())
        handle = await store.put(
            1, StoredResult(kind="t", data_class=DataClass.ADDRESSES, rows=[{"a": 1}], partial=True)
        )

        stored = await store.get(1, handle)

        assert stored is not None
        self.assertTrue(stored.partial)

    async def test_an_entry_written_without_the_flag_reads_as_complete(self) -> None:
        backend = InMemoryResultBackend()
        store = ResultStore(backend)
        handle = await store.put(
            1, StoredResult(kind="t", data_class=DataClass.ADDRESSES, rows=[{"a": 1}])
        )
        key = next(iter(backend._data))
        expiry, raw = backend._data[key]
        legacy = {k: v for k, v in json.loads(raw).items() if k != "partial"}
        backend._data[key] = (expiry, json.dumps(legacy))

        stored = await store.get(1, handle)

        assert stored is not None
        self.assertFalse(stored.partial)
