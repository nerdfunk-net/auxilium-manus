"""Per-filter Redis cache for the (otherwise live) Nautobot location query.

Nautobot resolves the child-location hierarchy server-side, so the location
filter can't be answered from the bulk device list; instead each distinct
filter's result is cached for a short TTL (``location_ttl``).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")
_OTHER_CREDS = NautobotCredentials(url="http://other.test", token="tok2")


def _gql_device(did: str, name: str, **over) -> dict:
    d = {
        "id": did,
        "name": name,
        "serial": "SN",
        "_custom_field_data": {"site_code": "NYC"},
        "primary_ip4": {"address": "10.0.0.1/24"},
        "status": {"name": "Active"},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "role": {"name": "leaf"},
        "location": {"name": "dc1"},
        "tags": [{"name": "prod"}],
        "platform": {"name": "ios", "network_driver": "ios"},
    }
    d.update(over)
    return d


class _FakeCache:
    """Dict-backed stand-in for RedisCacheService (get/set only)."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.ttls: dict[str, int] = {}
        self.get_error: Exception | None = None
        self.set_error: Exception | None = None

    def get(self, key: str):
        if self.get_error:
            raise self.get_error
        return self.store.get(key)

    def set(self, key: str, data, ttl_seconds: int) -> None:
        if self.set_error:
            raise self.set_error
        self.store[key] = data
        self.ttls[key] = ttl_seconds


def _service(
    graphql=None, cache=None, creds=_CREDS, location_ttl: int = 600
) -> NautobotSourceQueryService:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value=graphql or {"data": {"devices": []}})
    return NautobotSourceQueryService(
        nautobot, creds, cache, bulk_ttl=1800, location_ttl=location_ttl
    )


def _two_devices() -> dict:
    return {"data": {"devices": [_gql_device("a", "r1"), _gql_device("b", "r2")]}}


class LocationCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_miss_queries_nautobot_and_stores_result_with_location_ttl(self) -> None:
        cache = _FakeCache()
        svc = _service(_two_devices(), cache, location_ttl=420)

        devices = await svc._query_devices_by_location("Location A")

        self.assertEqual([d.id for d in devices], ["a", "b"])
        svc._nautobot.graphql_query.assert_awaited_once()
        (key,) = cache.store
        self.assertEqual(cache.ttls[key], 420)
        self.assertTrue(key.startswith("nautobot:devices:location:"))
        self.assertEqual(len(cache.store[key]), 2)

    async def test_hit_is_served_from_cache_without_calling_nautobot(self) -> None:
        cache = _FakeCache()
        first = _service(_two_devices(), cache)
        await first._query_devices_by_location("Location A")

        second = _service({"data": {"devices": []}}, cache)
        devices = await second._query_devices_by_location("Location A")

        second._nautobot.graphql_query.assert_not_awaited()
        self.assertEqual([d.id for d in devices], ["a", "b"])
        self.assertEqual(devices[0].primary_ip4, "10.0.0.1/24")
        self.assertEqual(devices[0].custom_fields, {"site_code": "NYC"})
        self.assertEqual(devices[0].tags, ["prod"])

    async def test_cached_devices_round_trip_every_field(self) -> None:
        cache = _FakeCache()
        live = await _service(_two_devices(), cache)._query_devices_by_location("dc1")

        cached = await _service(None, cache)._query_devices_by_location("dc1")

        self.assertEqual([d.model_dump() for d in cached], [d.model_dump() for d in live])

    async def test_equals_and_not_equals_and_each_filter_have_their_own_key(self) -> None:
        cache = _FakeCache()
        svc = _service(_two_devices(), cache)

        await svc._query_devices_by_location("dc1")
        await svc._query_devices_by_location("dc1", use_negation=True)
        await svc._query_devices_by_location("dc2")

        self.assertEqual(len(cache.store), 3)
        self.assertEqual(svc._nautobot.graphql_query.await_count, 3)
        modes = sorted(key.split(":")[4] for key in cache.store)
        self.assertEqual(modes, ["eq", "eq", "not"])

    async def test_locations_are_matched_exactly_never_by_substring(self) -> None:
        # "Location contains City" must not be possible: only the exact `location`
        # and `location__n` filters exist, and the value is passed through verbatim.
        svc = _service(_two_devices(), _FakeCache())

        await svc._query_devices_by_location("City")
        await svc._query_devices_by_location("City", use_negation=True)

        (eq_call, not_call) = svc._nautobot.graphql_query.await_args_list
        eq_query, eq_vars, _ = eq_call.args
        not_query, not_vars, _ = not_call.args
        self.assertIn("devices (location: $location_filter)", eq_query)
        self.assertIn("devices (location__n: $location_filter)", not_query)
        for query in (eq_query, not_query):
            self.assertNotIn("__ic", query)
            self.assertNotIn("contains", query)
        self.assertEqual(eq_vars, {"location_filter": ["City"]})
        self.assertEqual(not_vars, {"location_filter": ["City"]})

    async def test_there_is_no_contains_parameter_for_locations(self) -> None:
        svc = _service(_two_devices(), _FakeCache())

        with self.assertRaises(TypeError):
            await svc._query_devices_by_location("City", use_contains=True)  # type: ignore[call-arg]

    async def test_filter_is_whitespace_normalised_but_case_sensitive(self) -> None:
        cache = _FakeCache()
        svc = _service(_two_devices(), cache)

        await svc._query_devices_by_location("Location A")
        await svc._query_devices_by_location("  Location A  ")
        self.assertEqual(svc._nautobot.graphql_query.await_count, 1)

        await svc._query_devices_by_location("location a")
        self.assertEqual(svc._nautobot.graphql_query.await_count, 2)

    async def test_keys_are_safe_for_awkward_location_names(self) -> None:
        cache = _FakeCache()
        svc = _service(_two_devices(), cache)

        await svc._query_devices_by_location("Berlin: HQ / Floor 2 *")

        (key,) = cache.store
        self.assertNotIn(" ", key)
        self.assertNotIn("*", key)
        self.assertEqual(key.count(":"), 5)  # nautobot:devices:location:<scope>:<mode>:<name>

    async def test_cache_is_scoped_per_nautobot_instance(self) -> None:
        cache = _FakeCache()
        await _service(_two_devices(), cache, creds=_CREDS)._query_devices_by_location("dc1")

        other = _service(_two_devices(), cache, creds=_OTHER_CREDS)
        await other._query_devices_by_location("dc1")

        other._nautobot.graphql_query.assert_awaited_once()
        self.assertEqual(len(cache.store), 2)

    async def test_empty_result_is_not_cached(self) -> None:
        # A just-created location / just-added device must show up on the next run.
        cache = _FakeCache()
        svc = _service({"data": {"devices": []}}, cache)

        self.assertEqual(await svc._query_devices_by_location("dc1"), [])
        self.assertEqual(await svc._query_devices_by_location("dc1"), [])

        self.assertEqual(cache.store, {})
        self.assertEqual(svc._nautobot.graphql_query.await_count, 2)

    async def test_graphql_errors_are_never_cached(self) -> None:
        cache = _FakeCache()
        svc = _service(
            {"errors": [{"message": "boom"}], "data": {"devices": [_gql_device("a", "r1")]}},
            cache,
        )

        await svc._query_devices_by_location("dc1")

        self.assertEqual(cache.store, {})

    async def test_null_data_is_handled_and_not_cached(self) -> None:
        cache = _FakeCache()
        svc = _service({"errors": [{"message": "boom"}], "data": None}, cache)

        self.assertEqual(await svc._query_devices_by_location("dc1"), [])
        self.assertEqual(cache.store, {})

    async def test_redis_read_failure_falls_back_to_live_query(self) -> None:
        cache = _FakeCache()
        cache.get_error = RuntimeError("redis down")
        svc = _service(_two_devices(), cache)

        devices = await svc._query_devices_by_location("dc1")

        self.assertEqual(len(devices), 2)

    async def test_redis_write_failure_still_returns_devices(self) -> None:
        cache = _FakeCache()
        cache.set_error = RuntimeError("redis down")
        svc = _service(_two_devices(), cache)

        devices = await svc._query_devices_by_location("dc1")

        self.assertEqual(len(devices), 2)

    async def test_without_a_cache_service_every_call_is_live(self) -> None:
        svc = _service(_two_devices(), cache=None)

        await svc._query_devices_by_location("dc1")
        await svc._query_devices_by_location("dc1")

        self.assertEqual(svc._nautobot.graphql_query.await_count, 2)

    async def test_empty_filter_never_touches_cache_or_nautobot(self) -> None:
        cache = _FakeCache()
        svc = _service(_two_devices(), cache)

        self.assertEqual(await svc._query_devices_by_location("   "), [])

        svc._nautobot.graphql_query.assert_not_awaited()
        self.assertEqual(cache.store, {})

    async def test_default_location_ttl_is_ten_minutes(self) -> None:
        svc = NautobotSourceQueryService(MagicMock(), _CREDS, _FakeCache())
        self.assertEqual(svc._location_ttl, 600)


if __name__ == "__main__":
    unittest.main()
