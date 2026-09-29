"""Forced rebuild of the Nautobot device caches (the "Rebuild cache" button).

Unlike the 5-minute cron refresh, a rebuild drops every derived cache entry of
the Nautobot instance (location filters, per-device details and attributes)
even when nothing changed, then reloads all devices from Nautobot.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis

from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.query import DeviceQueryService
from services.sources.nautobot.query_service import NautobotSourceQueryService
from services.sources.nautobot.source_service import NautobotSourceService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")
_OTHER = NautobotCredentials(url="http://other.test", token="tok2")


def _gql(did: str, name: str, location: str = "dc1") -> dict:
    return {
        "id": did,
        "name": name,
        "serial": "SN",
        "_custom_field_data": {},
        "primary_ip4": {"address": "10.0.0.1/24"},
        "status": {"name": "Active"},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "role": {"name": "leaf"},
        "location": {"name": location},
        "tags": [],
        "platform": {"name": "ios", "network_driver": "ios"},
    }


def _cache() -> RedisCacheService:
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    with patch("services.cache.redis_cache_service.redis.from_url", return_value=fake):
        return RedisCacheService("redis://localhost:6379/0", key_prefix="test-cache")


def _keys(cache: RedisCacheService, pattern: str) -> list[str]:
    return sorted(cache._redis.scan_iter(f"test-cache:{pattern}"))


def _nautobot(devices: list[dict]) -> MagicMock:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value={"data": {"devices": devices}})
    return nautobot


class ForcedBulkRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_force_replaces_location_entries_even_when_nothing_changed(self) -> None:
        cache = _cache()
        devices = [_gql("a", "r1")]
        svc = NautobotSourceQueryService(_nautobot(devices), _CREDS, cache)
        await svc.refresh_bulk_cache()
        await svc._query_devices_by_location("dc1")
        (key,) = _keys(cache, "nautobot:devices:location:*")
        stale = [{"id": "stale", "name": "stale"}]
        cache._redis.set(key, json.dumps(stale), ex=600)  # a marker a real refresh wouldn't touch

        await svc.refresh_bulk_cache()  # unchanged data -> the entry is kept as is
        self.assertEqual(cache.get(key[len("test-cache:") :]), stale)

        await svc.refresh_bulk_cache(
            force_invalidate=True
        )  # rebuild -> dropped and re-cached fresh
        fresh = cache.get(key[len("test-cache:") :])
        self.assertEqual([d["id"] for d in fresh], ["a"])

    async def test_force_still_rewrites_the_bulk_entry(self) -> None:
        cache = _cache()
        svc = NautobotSourceQueryService(_nautobot([_gql("a", "r1")]), _CREDS, cache)

        count = await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(count, 1)
        self.assertEqual(len(cache.get(svc._bulk_cache_key)), 1)


class RewarmLocationFiltersTests(unittest.IsolatedAsyncioTestCase):
    """A forced rebuild re-runs the location filters that were cached, so the
    ones people actually use are warm again when it finishes."""

    def setUp(self) -> None:
        self.cache = _cache()
        self.devices = [_gql("a", "r1", "dc1"), _gql("b", "r2", "dc2")]

    def _svc(self, devices=None, creds=_CREDS) -> NautobotSourceQueryService:
        devices = self.devices if devices is None else devices
        return NautobotSourceQueryService(_nautobot(devices), creds, self.cache)

    def _location_calls(self, svc: NautobotSourceQueryService) -> list[tuple[str, list[str]]]:
        """(graphql text, location_filter variable) of every location query."""
        return [
            (call.args[0], call.args[1]["location_filter"])
            for call in svc._nautobot.graphql_query.await_args_list
            if call.args[1] and "location_filter" in call.args[1]
        ]

    async def _prime(self, *filters) -> None:
        svc = self._svc()
        await svc.refresh_bulk_cache()
        for name, negation in filters:
            await svc._query_devices_by_location(name, negation)

    async def test_previously_cached_filters_are_cached_again_after_a_rebuild(self) -> None:
        await self._prime(("dc1", False), ("dc2", False), ("dc2", True))
        before = _keys(self.cache, "nautobot:devices:location:*")
        self.assertEqual(len(before), 3)

        svc = self._svc()
        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(_keys(self.cache, "nautobot:devices:location:*"), before)
        texts = [text for text, _ in self._location_calls(svc)]
        self.assertEqual(len(texts), 3)
        self.assertEqual(sum("location__n:" in t for t in texts), 1)  # the "not dc2" filter
        self.assertFalse(any("__ic" in t or "contains" in t for t in texts))

    async def test_rewarmed_entries_hold_the_fresh_data(self) -> None:
        await self._prime(("dc1", False))
        new_devices = [*self.devices, _gql("c", "r3", "dc1")]

        await self._svc(new_devices).refresh_bulk_cache(force_invalidate=True)

        reader = self._svc([])  # would return nothing if it went to Nautobot
        devices = await reader._query_devices_by_location("dc1")
        reader._nautobot.graphql_query.assert_not_awaited()
        self.assertEqual({d.id for d in devices}, {"a", "b", "c"})

    async def test_awkward_location_names_round_trip(self) -> None:
        await self._prime(("Berlin: HQ / Floor 2 *", False))

        svc = self._svc()
        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(self._location_calls(svc)[0][1], ["Berlin: HQ / Floor 2 *"])
        self.assertEqual(len(_keys(self.cache, "nautobot:devices:location:*")), 1)

    async def test_filters_that_were_never_cached_are_not_queried(self) -> None:
        await self._prime(("dc1", False))

        svc = self._svc()
        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual([f for _, f in self._location_calls(svc)], [["dc1"]])

    async def test_nothing_to_rewarm_costs_only_the_bulk_query(self) -> None:
        await self._prime()

        svc = self._svc()
        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(svc._nautobot.graphql_query.await_count, 1)

    async def test_a_location_that_is_now_empty_is_not_recached(self) -> None:
        await self._prime(("dc1", False))

        # The location now has no devices (the shared mock answers every query alike).
        await self._svc([]).refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(_keys(self.cache, "nautobot:devices:location:*"), [])

    async def test_one_failing_filter_does_not_fail_the_rebuild_or_the_others(self) -> None:
        await self._prime(("dc1", False), ("dc2", False))
        svc = self._svc()
        real = svc._nautobot.graphql_query

        async def flaky(query, variables, credentials):
            if variables and variables.get("location_filter") == ["dc1"]:
                raise RuntimeError("nautobot hiccup")
            return await real(query, variables, credentials)

        svc._nautobot.graphql_query = AsyncMock(side_effect=flaky)

        count = await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(count, 2)
        keys = _keys(self.cache, "nautobot:devices:location:*")
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].endswith(":eq:dc2"))

    async def test_a_plain_change_driven_invalidation_stays_lazy(self) -> None:
        await self._prime(("dc1", False))

        svc = self._svc([*self.devices, _gql("c", "r3", "dc1")])
        await svc.refresh_bulk_cache()  # cron path: data changed, not forced

        self.assertEqual(_keys(self.cache, "nautobot:devices:location:*"), [])
        self.assertEqual(self._location_calls(svc), [])

    async def test_other_instances_filters_are_neither_dropped_nor_queried(self) -> None:
        await self._prime(("dc1", False))
        other = self._svc(creds=_OTHER)
        await other.refresh_bulk_cache()
        await other._query_devices_by_location("dc9")
        other_keys = [
            k for k in _keys(self.cache, "nautobot:devices:location:*") if _OTHER.cache_scope in k
        ]

        svc = self._svc()
        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual([f for _, f in self._location_calls(svc)], [["dc1"]])
        self.assertEqual(
            [
                k
                for k in _keys(self.cache, "nautobot:devices:location:*")
                if _OTHER.cache_scope in k
            ],
            other_keys,
        )

    async def test_rewarming_is_bounded_in_parallel(self) -> None:
        names = [f"loc{i}" for i in range(20)]
        await self._prime(*[(n, False) for n in names])
        svc = self._svc()
        real = svc._nautobot.graphql_query
        in_flight = 0
        peak = 0

        async def tracked(query, variables, credentials):
            nonlocal in_flight, peak
            if variables and "location_filter" in variables:
                in_flight += 1
                peak = max(peak, in_flight)
                await asyncio.sleep(0)
                in_flight -= 1
            return await real(query, variables, credentials)

        svc._nautobot.graphql_query = AsyncMock(side_effect=tracked)

        await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(len(_keys(self.cache, "nautobot:devices:location:*")), 20)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 5)

    async def test_failed_nautobot_fetch_drops_and_rewarms_nothing(self) -> None:
        await self._prime(("dc1", False))
        before = _keys(self.cache, "nautobot:devices:location:*")
        svc = self._svc()
        svc._nautobot.graphql_query = AsyncMock(side_effect=RuntimeError("nautobot down"))

        with self.assertRaises(RuntimeError):
            await svc.refresh_bulk_cache(force_invalidate=True)

        self.assertEqual(_keys(self.cache, "nautobot:devices:location:*"), before)


class DeviceQueryInvalidationTests(unittest.TestCase):
    def test_invalidate_cache_drops_details_and_attributes_of_this_instance_only(self) -> None:
        cache = _cache()
        mine = DeviceQueryService(MagicMock(), _CREDS, cache)
        theirs = DeviceQueryService(MagicMock(), _OTHER, cache)
        for svc in (mine, theirs):
            cache.set(svc._details_cache_key("d1"), {"x": 1}, 60)
            cache.set(svc._attributes_cache_key("d1", ["a"]), {"x": 1}, 60)
        cache.set("unrelated:key", 1, 60)

        removed = mine.invalidate_cache()

        self.assertEqual(removed, 2)
        self.assertIsNone(cache.get(mine._details_cache_key("d1")))
        self.assertIsNone(cache.get(mine._attributes_cache_key("d1", ["a"])))
        self.assertIsNotNone(cache.get(theirs._details_cache_key("d1")))
        self.assertIsNotNone(cache.get(theirs._attributes_cache_key("d1", ["a"])))
        self.assertEqual(cache.get("unrelated:key"), 1)

    def test_invalidate_cache_without_a_cache_service_is_a_noop(self) -> None:
        self.assertEqual(DeviceQueryService(MagicMock(), _CREDS, None).invalidate_cache(), 0)

    def test_invalidate_cache_never_raises(self) -> None:
        cache = MagicMock()
        cache.clear_namespace.side_effect = RuntimeError("down")
        self.assertEqual(DeviceQueryService(MagicMock(), _CREDS, cache).invalidate_cache(), 0)


class SourceServiceForceTests(unittest.IsolatedAsyncioTestCase):
    def _service(self) -> NautobotSourceService:
        svc = NautobotSourceService(MagicMock(), _CREDS, persistence_service=MagicMock())
        svc.query_service = MagicMock()
        svc.query_service.refresh_bulk_cache = AsyncMock(return_value=7)
        svc.device_query_service = MagicMock()
        return svc

    async def test_default_refresh_leaves_per_device_caches_alone(self) -> None:
        svc = self._service()

        self.assertEqual(await svc.refresh_bulk_device_cache(), 7)

        svc.query_service.refresh_bulk_cache.assert_awaited_once_with(force_invalidate=False)
        svc.device_query_service.invalidate_cache.assert_not_called()

    async def test_forced_refresh_also_drops_per_device_caches(self) -> None:
        svc = self._service()

        self.assertEqual(await svc.refresh_bulk_device_cache(force=True), 7)

        svc.query_service.refresh_bulk_cache.assert_awaited_once_with(force_invalidate=True)
        svc.device_query_service.invalidate_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
