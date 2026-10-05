"""Indexed Nautobot device cache: one hash of devices + one hash index per attribute.

role/status/device_type/manufacturer/platform equality filters must read only the
matching devices from Redis (index -> HMGET), never the whole list. Runs against a
real RedisCacheService backed by fakeredis so the actual key layout is exercised.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis

from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")
_OTHER = NautobotCredentials(url="http://other.test", token="tok2")


def _gql(did: str, role: str | None = "leaf", status: str = "Active", **over) -> dict:
    d = {
        "id": did,
        "name": f"dev-{did}",
        "serial": "SN",
        "_custom_field_data": {},
        "primary_ip4": {"address": "10.0.0.1/24"},
        "status": {"name": status},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "role": {"name": role} if role else None,
        "location": {"name": "dc1"},
        "tags": [],
        "platform": {"name": "ios", "network_driver": "ios"},
    }
    d.update(over)
    return d


def _cache() -> RedisCacheService:
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    with patch("services.cache.redis_cache_service.redis.from_url", return_value=fake):
        return RedisCacheService("redis://localhost:6379/0", key_prefix="test-cache")


def _service(cache: RedisCacheService, devices: list[dict], creds=_CREDS):
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value={"data": {"devices": devices}})
    svc = NautobotSourceQueryService(nautobot, creds, cache, bulk_ttl=1800, location_ttl=600)
    return svc, nautobot


def _retag(cache: RedisCacheService, svc, device_id: str, **fields) -> None:
    """Change fields of a device body in the data hash, leaving the indexes stale."""
    key = f"test-cache:{svc._bulk_cache_key}"
    body = json.loads(cache._redis.hget(key, device_id))
    cache._redis.hset(key, device_id, json.dumps({**body, **fields}))


def _ids(devices) -> list[str]:
    return sorted(d.id for d in devices)


_FLEET = [
    _gql("a", role="leaf"),
    _gql("b", role="server", status="Planned"),
    _gql("c", role="server"),
    _gql("d", role=None),
    _gql(
        "e",
        role="spine",
        device_type={"model": "QFX", "manufacturer": {"name": "Juniper"}},
        platform={"name": "junos", "network_driver": "junos"},
    ),
]


class IndexedReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cache = _cache()
        writer, _ = _service(self.cache, _FLEET)
        await writer.refresh_bulk_cache()
        # A fresh instance per "request": nothing memoised in process.
        self.svc, self.nautobot = _service(self.cache, _FLEET)

    async def test_refresh_writes_data_hash_and_indexes_with_ttl(self) -> None:
        redis = self.cache._redis
        keys = sorted(redis.scan_iter("test-cache:nautobot:devices:*"))
        scope = _CREDS.cache_scope
        self.assertEqual(
            keys,
            sorted(
                [
                    f"test-cache:nautobot:devices:data:{scope}",
                    *[
                        f"test-cache:nautobot:devices:idx:{scope}:{f}"
                        for f in ("role", "status", "device_type", "manufacturer", "platform")
                    ],
                ]
            ),
        )
        for key in keys:
            self.assertGreater(redis.ttl(key), 0)

    async def test_role_filter_reads_only_matching_devices(self) -> None:
        with (
            patch.object(self.cache, "hvals_json", wraps=self.cache.hvals_json) as hvals,
            patch.object(self.cache, "hmget_json", wraps=self.cache.hmget_json) as hmget,
        ):
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        hvals.assert_not_called()
        (_, fields), _ = hmget.call_args
        self.assertEqual(sorted(fields), ["b", "c"])
        self.nautobot.graphql_query.assert_not_awaited()

    async def test_status_device_type_manufacturer_platform_use_the_index(self) -> None:
        with patch.object(self.cache, "hvals_json") as hvals:
            self.assertEqual(_ids(await self.svc._query_devices_by_status("Planned")), ["b"])
            self.assertEqual(_ids(await self.svc._query_devices_by_devicetype("QFX")), ["e"])
            self.assertEqual(
                _ids(await self.svc._query_devices_by_manufacturer("Cisco")),
                ["a", "b", "c", "d"],
            )
            self.assertEqual(_ids(await self.svc._query_devices_by_platform("junos")), ["e"])
        hvals.assert_not_called()

    async def test_negation_includes_devices_without_a_value(self) -> None:
        result = await self.svc._query_devices_by_role("server", use_negation=True)
        self.assertEqual(_ids(result), ["a", "d", "e"])  # "d" has no role at all
        result = await self.svc._query_devices_by_devicetype("C9300", use_negation=True)
        self.assertEqual(_ids(result), ["e"])
        result = await self.svc._query_devices_by_manufacturer("Juniper", use_negation=True)
        self.assertEqual(_ids(result), ["a", "b", "c", "d"])

    async def test_unknown_value_on_warm_cache_is_empty_without_calling_nautobot(self) -> None:
        self.assertEqual(await self.svc._query_devices_by_role("firewall"), [])
        self.assertEqual(
            _ids(await self.svc._query_devices_by_role("firewall", use_negation=True)),
            ["a", "b", "c", "d", "e"],
        )
        self.nautobot.graphql_query.assert_not_awaited()

    async def test_empty_value_returns_empty(self) -> None:
        self.assertEqual(await self.svc._query_devices_by_role(""), [])
        self.assertEqual(await self.svc._query_devices_by_status("  "), [])

    async def test_missing_data_entry_discards_the_partial_result_and_scans(self) -> None:
        # index and data hash disagree (torn read / partial eviction): never answer from
        # half of the id list, fall back to the single-snapshot full list instead
        self.cache._redis.hdel(f"test-cache:{self.svc._bulk_cache_key}", "b")
        with patch.object(self.cache, "hvals_json", wraps=self.cache.hvals_json) as hvals:
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["c"])
        hvals.assert_called_once()

    async def test_body_that_no_longer_matches_the_index_is_never_returned(self) -> None:
        # the cron swapped the hashes between our index read and our HMGET: the old
        # index still lists "b" as a server, the new data says it is a leaf
        _retag(self.cache, self.svc, "b", role="leaf")
        self.assertEqual(_ids(await self.svc._query_devices_by_role("server")), ["c"])
        self.assertEqual(
            _ids(await self.svc._query_devices_by_role("leaf")), ["a", "b"]
        )  # full-list answer, one snapshot

    async def test_failed_index_read_is_not_an_authoritative_empty_result(self) -> None:
        # HGET dies but the following EXISTS works (reconnect): must fall back, not answer []
        real_hget = self.cache._redis.hget
        calls = {"n": 0}

        def flaky_hget(key, field):
            if ":idx:" in key:
                calls["n"] += 1
                raise ConnectionError("dropped")
            return real_hget(key, field)

        with patch.object(self.cache._redis, "hget", side_effect=flaky_hget):
            equal = await self.svc._query_devices_by_role("server")
            ids = await self.svc._ids_by_attribute("role", "server", negate=True)
        self.assertGreater(calls["n"], 0)
        self.assertEqual(_ids(equal), ["b", "c"])
        self.assertEqual(ids, {"a", "d", "e"})  # not "every device"

    async def test_corrupt_index_field_falls_back_instead_of_answering_empty(self) -> None:
        self.cache._redis.hset(f"test-cache:{self.svc._index_key('role')}", "server", "{broken")
        self.assertEqual(_ids(await self.svc._query_devices_by_role("server")), ["b", "c"])
        self.assertEqual(
            await self.svc._ids_by_attribute("role", "server", negate=True), {"a", "d", "e"}
        )

    async def test_missing_index_falls_back_to_full_scan(self) -> None:
        self.cache._redis.delete(f"test-cache:{self.svc._index_key('role')}")
        result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])

    async def test_in_memory_full_list_is_reused_without_redis_calls(self) -> None:
        await self.svc._get_all_devices_cached()
        with (
            patch.object(self.cache, "hget_json") as hget,
            patch.object(self.cache, "hmget_json") as hmget,
        ):
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        hget.assert_not_called()
        hmget.assert_not_called()

    async def test_index_read_error_falls_back_to_the_full_cached_list(self) -> None:
        with patch.object(self.cache, "hget_json", side_effect=RuntimeError("down")):
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        self.nautobot.graphql_query.assert_not_awaited()  # full list still served by Redis

    async def test_hmget_failure_falls_back_to_the_full_cached_list(self) -> None:
        with patch.object(self.cache, "hmget_json", return_value=None):
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        self.nautobot.graphql_query.assert_not_awaited()

    async def test_redis_fully_down_falls_back_to_live(self) -> None:
        with (
            patch.object(self.cache, "hget_json", side_effect=RuntimeError("down")),
            patch.object(self.cache, "hvals_json", return_value=None),
        ):
            result = await self.svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        self.nautobot.graphql_query.assert_awaited_once()

    async def test_full_scan_reads_every_device(self) -> None:
        devices = await self.svc._get_all_devices_cached()
        self.assertEqual(_ids(devices), ["a", "b", "c", "d", "e"])
        self.nautobot.graphql_query.assert_not_awaited()


class IdsFirstApiTests(unittest.IsolatedAsyncioTestCase):
    """ids from the index (no parsing) and fetching devices by id, used by the evaluator."""

    async def asyncSetUp(self) -> None:
        self.cache = _cache()
        writer, _ = _service(self.cache, _FLEET)
        await writer.refresh_bulk_cache()
        self.svc, self.nautobot = _service(self.cache, _FLEET)

    async def test_ids_by_attribute_reads_only_the_index(self) -> None:
        with (
            patch.object(self.cache, "hvals_json") as hvals,
            patch.object(self.cache, "hmget_json") as hmget,
        ):
            self.assertEqual(await self.svc._ids_by_attribute("role", "server"), {"b", "c"})
        hvals.assert_not_called()
        hmget.assert_not_called()

    async def test_ids_by_attribute_negation_includes_devices_without_a_value(self) -> None:
        self.assertEqual(
            await self.svc._ids_by_attribute("role", "server", negate=True), {"a", "d", "e"}
        )

    async def test_ids_by_attribute_unknown_value_warm_cache(self) -> None:
        self.assertEqual(await self.svc._ids_by_attribute("role", "firewall"), set())
        self.nautobot.graphql_query.assert_not_awaited()

    async def test_ids_by_attribute_cold_cache_uses_live_data(self) -> None:
        svc, nautobot = _service(_cache(), _FLEET)
        self.assertEqual(await svc._ids_by_attribute("role", "server"), {"b", "c"})
        nautobot.graphql_query.assert_awaited_once()

    async def test_devices_by_ids_fetches_only_those(self) -> None:
        with (
            patch.object(self.cache, "hvals_json") as hvals,
            patch.object(self.cache, "hmget_json", wraps=self.cache.hmget_json) as hmget,
        ):
            devices = await self.svc._devices_by_ids({"b", "e"})
        self.assertEqual(_ids(devices), ["b", "e"])
        hvals.assert_not_called()
        (_, fields), _ = hmget.call_args
        self.assertEqual(sorted(fields), ["b", "e"])

    async def test_devices_by_ids_empty_set_touches_nothing(self) -> None:
        with patch.object(self.cache, "hmget_json") as hmget:
            self.assertEqual(await self.svc._devices_by_ids(set()), [])
        hmget.assert_not_called()

    async def test_devices_by_ids_uses_memoised_list(self) -> None:
        await self.svc._get_all_devices_cached()
        with patch.object(self.cache, "hmget_json") as hmget:
            self.assertEqual(_ids(await self.svc._devices_by_ids({"a", "c"})), ["a", "c"])
        hmget.assert_not_called()

    async def test_devices_by_ids_with_predicates_rejects_stale_bodies(self) -> None:
        _retag(self.cache, self.svc, "c", role="leaf")
        devices = await self.svc._devices_by_ids({"b", "c"}, [("role", "server", False)])
        self.assertEqual(_ids(devices), ["b"])  # recomputed from one snapshot, c is a leaf now

    async def test_devices_by_ids_falls_back_to_full_list_when_data_is_gone(self) -> None:
        with patch.object(self.cache, "hmget_json", return_value=[None, None]):
            self.assertEqual(_ids(await self.svc._devices_by_ids({"a", "c"})), ["a", "c"])

    async def test_negated_attribute_filter_uses_the_full_list(self) -> None:
        # the complement is usually most of the fleet: HVALS beats a huge HMGET
        with (
            patch.object(self.cache, "hmget_json") as hmget,
            patch.object(self.cache, "hvals_json", wraps=self.cache.hvals_json) as hvals,
        ):
            result = await self.svc._query_devices_by_role("server", use_negation=True)
        self.assertEqual(_ids(result), ["a", "d", "e"])
        hmget.assert_not_called()
        hvals.assert_called_once()

    async def test_narrowed_to_scopes_the_full_list_and_restores_it(self) -> None:
        narrowed = await self.svc._devices_by_ids({"b", "c", "e"})
        with self.svc.narrowed_to(narrowed):
            self.assertEqual(_ids(await self.svc._get_all_devices_cached()), ["b", "c", "e"])
            by_name = await self.svc._query_devices_by_name("dev-", use_contains=True)
            self.assertEqual(_ids(by_name), ["b", "c", "e"])
        self.assertEqual(_ids(await self.svc._get_all_devices_cached()), ["a", "b", "c", "d", "e"])

    async def test_narrowed_to_restores_the_previous_list_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.svc.narrowed_to([]):
                raise RuntimeError("boom")
        self.assertIsNone(self.svc._devices_cache)


class ColdCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_cache_uses_live_data_and_filters(self) -> None:
        svc, nautobot = _service(_cache(), _FLEET)
        result = await svc._query_devices_by_role("server")
        self.assertEqual(_ids(result), ["b", "c"])
        nautobot.graphql_query.assert_awaited_once()

    async def test_without_cache_service_uses_live_data(self) -> None:
        nautobot = MagicMock()
        nautobot.graphql_query = AsyncMock(return_value={"data": {"devices": _FLEET}})
        svc = NautobotSourceQueryService(nautobot, _CREDS, None)
        self.assertEqual(_ids(await svc._query_devices_by_role("leaf")), ["a"])


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_replaces_indexes_when_a_device_changes_role(self) -> None:
        cache = _cache()
        first, _ = _service(cache, _FLEET)
        await first.refresh_bulk_cache()
        moved = [_gql("a", role="server") if d["id"] == "a" else d for d in _FLEET]
        second, _ = _service(cache, moved)
        await second.refresh_bulk_cache()

        reader, _ = _service(cache, [])
        self.assertEqual(_ids(await reader._query_devices_by_role("server")), ["a", "b", "c"])
        self.assertEqual(await reader._query_devices_by_role("leaf"), [])

    async def test_refresh_returns_count_and_survives_write_failure(self) -> None:
        cache = _cache()
        svc, _ = _service(cache, _FLEET)
        with patch.object(cache, "replace_hashes", return_value=False):
            self.assertEqual(await svc.refresh_bulk_cache(), 5)

    async def test_refresh_with_no_devices_clears_the_cache(self) -> None:
        cache = _cache()
        first, _ = _service(cache, _FLEET)
        await first.refresh_bulk_cache()
        empty, _ = _service(cache, [])
        self.assertEqual(await empty.refresh_bulk_cache(), 0)
        self.assertFalse(cache.hash_exists(empty._bulk_cache_key))

    async def test_scopes_are_isolated(self) -> None:
        cache = _cache()
        mine, _ = _service(cache, _FLEET)
        other, _ = _service(cache, [_gql("z", role="server")], creds=_OTHER)
        await mine.refresh_bulk_cache()
        await other.refresh_bulk_cache()

        reader_mine, _ = _service(cache, [])
        reader_other, _ = _service(cache, [], creds=_OTHER)
        self.assertEqual(_ids(await reader_mine._query_devices_by_role("server")), ["b", "c"])
        self.assertEqual(_ids(await reader_other._query_devices_by_role("server")), ["z"])


if __name__ == "__main__":
    unittest.main()
