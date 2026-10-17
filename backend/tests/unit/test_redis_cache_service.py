"""Tests for services/cache/redis_cache_service.py against fakeredis."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import fakeredis

from services.cache.redis_cache_service import RedisCacheService


def _service(prefix: str = "test-cache") -> RedisCacheService:
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    with patch("services.cache.redis_cache_service.redis.from_url", return_value=fake):
        return RedisCacheService("redis://localhost:6379/0", key_prefix=prefix)


class RedisCacheServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _service()
        self.redis = self.service._redis

    def test_init_sets_start_time_once(self) -> None:
        self.assertTrue(self.redis.exists("test-cache:start_time"))

    def test_make_key(self) -> None:
        self.assertEqual(self.service._make_key("foo"), "test-cache:foo")

    def test_ping_delegates(self) -> None:
        self.service.ping()  # no raise

    def test_set_get_roundtrip(self) -> None:
        self.service.set("k1", {"a": 1, "b": [2, 3]}, ttl_seconds=60)
        self.assertEqual(self.service.get("k1"), {"a": 1, "b": [2, 3]})

    def test_get_miss_returns_none(self) -> None:
        self.assertIsNone(self.service.get("absent"))

    def test_get_corrupt_json_deletes_and_returns_none(self) -> None:
        self.redis.set("test-cache:bad", "{not json")
        self.assertIsNone(self.service.get("bad"))
        self.assertFalse(self.redis.exists("test-cache:bad"))

    def test_get_error_path_returns_none(self) -> None:
        with patch.object(self.service._redis, "get", side_effect=RuntimeError("down")):
            self.assertIsNone(self.service.get("k"))

    def test_set_non_serializable_is_swallowed(self) -> None:
        self.service.set("k", {1, 2, 3}, ttl_seconds=60)  # set() is not JSON-serializable
        self.assertIsNone(self.service.get("k"))

    def test_set_error_path_is_swallowed(self) -> None:
        with patch.object(self.service._redis, "setex", side_effect=RuntimeError("down")):
            self.service.set("k", {"ok": 1}, ttl_seconds=60)  # no raise

    def test_delete_existing_and_missing(self) -> None:
        self.service.set("d1", {"x": 1}, ttl_seconds=60)
        self.assertTrue(self.service.delete("d1"))
        self.assertFalse(self.service.delete("d1"))

    def test_delete_error_path(self) -> None:
        with patch.object(self.service._redis, "delete", side_effect=RuntimeError("down")):
            self.assertFalse(self.service.delete("d1"))

    def test_clear_namespace(self) -> None:
        self.service.set("ns:a", 1, ttl_seconds=60)
        self.service.set("ns:b", 2, ttl_seconds=60)
        self.service.set("other:c", 3, ttl_seconds=60)
        self.assertEqual(self.service.clear_namespace("ns"), 2)
        self.assertEqual(self.service.clear_namespace("ns"), 0)
        self.assertEqual(self.service.get("other:c"), 3)

    def test_clear_namespace_error_path(self) -> None:
        with patch.object(self.service._redis, "keys", side_effect=RuntimeError("down")):
            self.assertEqual(self.service.clear_namespace("ns"), 0)

    def test_list_keys_returns_user_facing_keys_of_the_namespace_only(self) -> None:
        self.service.set("ns:a", 1, ttl_seconds=60)
        self.service.set("ns:b:c", 2, ttl_seconds=60)
        self.service.set("other:x", 3, ttl_seconds=60)
        self.service.set("ns", 4, ttl_seconds=60)  # the namespace name itself is not inside it

        self.assertEqual(self.service.list_keys("ns"), ["ns:a", "ns:b:c"])

    def test_list_keys_empty_and_error_paths(self) -> None:
        self.assertEqual(self.service.list_keys("nothing"), [])
        with patch.object(self.service._redis, "scan_iter", side_effect=RuntimeError("down")):
            self.assertEqual(self.service.list_keys("ns"), [])

    def test_clear_all_excludes_stats_and_start_time(self) -> None:
        self.service.set("a", 1, ttl_seconds=60)
        self.service.set("b", 2, ttl_seconds=60)
        self.assertEqual(self.service.clear_all(), 2)
        self.assertTrue(self.redis.exists("test-cache:start_time"))

    def test_clear_all_error_path(self) -> None:
        with patch.object(self.service._redis, "keys", side_effect=RuntimeError("down")):
            self.assertEqual(self.service.clear_all(), 0)

    def test_get_entries_reports_no_expiry_as_zero_ttl(self) -> None:
        self.redis.set("test-cache:forever", '{"v": 1}')  # no TTL
        entries = {e["key"]: e for e in self.service.get_entries()}
        self.assertEqual(entries["forever"]["ttl_seconds"], 0)

    def test_stats_reports_hits_misses_and_namespaces(self) -> None:
        self.service.set("nautobot:devices:1", {"x": 1}, ttl_seconds=60)
        self.service.get("nautobot:devices:1")  # hit
        self.service.get("nautobot:devices:missing")  # miss
        stats = self.service.stats()
        self.assertEqual(stats["overview"]["total_items"], 1)
        self.assertGreaterEqual(stats["performance"]["cache_hits"], 1)
        self.assertGreaterEqual(stats["performance"]["cache_misses"], 1)
        self.assertIn("nautobot", stats["namespaces"])
        self.assertIn("nautobot:devices:1", stats["keys"])

    def test_stats_error_path(self) -> None:
        with patch.object(self.service._redis, "keys", side_effect=RuntimeError("down")):
            stats = self.service.stats()
        self.assertEqual(stats["overview"]["total_items"], 0)
        self.assertIn("error", stats["overview"])

    def test_get_entries_lists_ttl_and_namespace(self) -> None:
        self.service.set("group:one", {"v": 1}, ttl_seconds=120)
        self.service.set("standalone", {"v": 2}, ttl_seconds=120)
        entries = self.service.get_entries()
        keys = [e["key"] for e in entries]
        self.assertEqual(keys, ["group:one", "standalone"])
        by_key = {e["key"]: e for e in entries}
        self.assertEqual(by_key["group:one"]["namespace"], "group")
        self.assertEqual(by_key["standalone"]["namespace"], "default")
        self.assertGreater(by_key["group:one"]["ttl_seconds"], 0)

    def test_get_entries_error_path(self) -> None:
        with patch.object(self.service._redis, "keys", side_effect=RuntimeError("down")):
            self.assertEqual(self.service.get_entries(), [])

    def test_get_namespace_info(self) -> None:
        self.service.set("ns:x", 1, ttl_seconds=60)
        self.service.set("ns:y", 2, ttl_seconds=60)
        info = self.service.get_namespace_info("ns")
        self.assertEqual(info["total_entries"], 2)
        self.assertEqual(info["namespace"], "ns")

    def test_get_namespace_info_error_path(self) -> None:
        with patch.object(self.service._redis, "keys", side_effect=RuntimeError("down")):
            info = self.service.get_namespace_info("ns")
        self.assertEqual(info["total_entries"], 0)

    def test_get_performance_metrics(self) -> None:
        self.service.set("m", 1, ttl_seconds=60)
        self.service.get("m")
        metrics = self.service.get_performance_metrics()
        self.assertGreaterEqual(metrics["cache_hits"], 1)
        self.assertEqual(metrics["current_entries"], 1)

    def test_get_performance_metrics_error_path(self) -> None:
        with patch.object(self.service._redis, "hgetall", side_effect=RuntimeError("down")):
            metrics = self.service.get_performance_metrics()
        self.assertEqual(metrics["total_requests"], 0)

    def test_cleanup_expired_is_noop(self) -> None:
        self.assertEqual(self.service.cleanup_expired(), 0)


class RedisHashHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _service()
        self.redis = self.service._redis

    def test_replace_hashes_roundtrip_and_ttl(self) -> None:
        ok = self.service.replace_hashes(
            {"h": {"a": {"id": "a"}, "b": {"id": "b"}}, "idx": {"leaf": ["a", "b"]}},
            ttl_seconds=60,
        )
        self.assertTrue(ok)
        self.assertEqual(self.service.hgetall_json("h"), {"a": {"id": "a"}, "b": {"id": "b"}})
        self.assertEqual(self.service.hget_json("idx", "leaf"), ["a", "b"])
        for key in ("test-cache:h", "test-cache:idx"):
            self.assertGreater(self.redis.ttl(key), 0)

    def test_replace_hashes_replaces_whole_key_and_leaves_no_tmp_keys(self) -> None:
        self.service.replace_hashes({"h": {"a": 1, "b": 2}}, ttl_seconds=60)
        self.service.replace_hashes({"h": {"c": 3}}, ttl_seconds=60)
        self.assertEqual(self.service.hgetall_json("h"), {"c": 3})
        self.assertEqual(sorted(self.redis.scan_iter("test-cache:h*")), ["test-cache:h"])

    def test_replace_hashes_empty_mapping_deletes_live_key(self) -> None:
        self.service.replace_hashes({"h": {"a": 1}}, ttl_seconds=60)
        self.assertTrue(self.service.replace_hashes({"h": {}}, ttl_seconds=60))
        self.assertFalse(self.redis.exists("test-cache:h"))

    def test_replace_hashes_failure_keeps_old_data(self) -> None:
        self.service.replace_hashes({"h": {"a": 1}}, ttl_seconds=60)
        with patch.object(self.service._redis, "pipeline", side_effect=RuntimeError("down")):
            self.assertFalse(self.service.replace_hashes({"h": {"z": 9}}, ttl_seconds=60))
        self.assertEqual(self.service.hgetall_json("h"), {"a": 1})

    def test_replace_hashes_non_serializable_is_rejected_without_touching_redis(self) -> None:
        self.service.replace_hashes({"h": {"a": 1}}, ttl_seconds=60)
        self.assertFalse(self.service.replace_hashes({"h": {"z": {1, 2}}}, ttl_seconds=60))
        self.assertEqual(self.service.hgetall_json("h"), {"a": 1})

    def test_hget_json_returns_none_only_when_the_field_is_absent(self) -> None:
        self.assertIsNone(self.service.hget_json("h", "nope"))
        self.service.replace_hashes({"h": {"a": 1}}, ttl_seconds=60)
        self.assertIsNone(self.service.hget_json("h", "nope"))

    def test_hget_json_raises_on_redis_error_instead_of_looking_absent(self) -> None:
        with patch.object(self.service._redis, "hget", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                self.service.hget_json("h", "a")

    def test_hget_json_raises_on_corrupt_json_instead_of_looking_absent(self) -> None:
        self.redis.hset("test-cache:h", "bad", "{not json")
        with self.assertRaises(ValueError):
            self.service.hget_json("h", "bad")

    def test_hmget_json_is_aligned_with_fields_and_none_for_missing(self) -> None:
        self.service.replace_hashes({"h": {"a": {"id": "a"}, "c": {"id": "c"}}}, ttl_seconds=60)
        self.assertEqual(
            self.service.hmget_json("h", ["a", "b", "c"]), [{"id": "a"}, None, {"id": "c"}]
        )

    def test_hmget_json_empty_fields_and_error(self) -> None:
        self.assertEqual(self.service.hmget_json("h", []), [])
        with patch.object(self.service._redis, "hmget", side_effect=RuntimeError("down")):
            self.assertIsNone(self.service.hmget_json("h", ["a"]))

    def test_hvals_json_returns_values_or_none_when_absent(self) -> None:
        self.assertIsNone(self.service.hvals_json("h"))
        self.service.replace_hashes({"h": {"a": {"id": "a"}, "b": {"id": "b"}}}, ttl_seconds=60)
        self.assertEqual(
            sorted(self.service.hvals_json("h") or [], key=lambda d: d["id"]),
            [{"id": "a"}, {"id": "b"}],
        )

    def test_hvals_json_skips_corrupt_entries(self) -> None:
        self.service.replace_hashes({"h": {"a": {"id": "a"}}}, ttl_seconds=60)
        self.redis.hset("test-cache:h", "bad", "{not json")
        self.assertEqual(self.service.hvals_json("h"), [{"id": "a"}])

    def test_hkeys_and_hash_exists(self) -> None:
        self.assertEqual(self.service.hkeys("h"), [])
        self.assertFalse(self.service.hash_exists("h"))
        self.service.replace_hashes({"h": {"a": 1, "b": 2}}, ttl_seconds=60)
        self.assertEqual(sorted(self.service.hkeys("h")), ["a", "b"])
        self.assertTrue(self.service.hash_exists("h"))

    def test_hash_exists_and_hkeys_error_paths(self) -> None:
        with patch.object(self.service._redis, "exists", side_effect=RuntimeError("down")):
            self.assertFalse(self.service.hash_exists("h"))
        with patch.object(self.service._redis, "hkeys", side_effect=RuntimeError("down")):
            self.assertEqual(self.service.hkeys("h"), [])

    def test_hgetall_json_absent_and_error(self) -> None:
        self.assertIsNone(self.service.hgetall_json("h"))
        with patch.object(self.service._redis, "hgetall", side_effect=RuntimeError("down")):
            self.assertIsNone(self.service.hgetall_json("h"))


if __name__ == "__main__":
    unittest.main()
