"""The 5-minute bulk-refresh cron also invalidates the cached location filters
when Nautobot's device data changed, so a new/moved device shows up on the next
cron cycle instead of after the location-cache TTL.

Runs against a real RedisCacheService backed by fakeredis so the actual key
patterns (and per-instance scoping) are exercised.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis

from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")
_OTHER = NautobotCredentials(url="http://other.test", token="tok2")


def _gql(did: str, name: str, location: str = "dc1", ip: str = "10.0.0.1/24", **over) -> dict:
    d = {
        "id": did,
        "name": name,
        "serial": "SN",
        "_custom_field_data": {},
        "primary_ip4": {"address": ip},
        "status": {"name": "Active"},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "role": {"name": "leaf"},
        "location": {"name": location},
        "tags": [{"name": "prod"}],
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
    return NautobotSourceQueryService(nautobot, creds, cache, bulk_ttl=1800, location_ttl=600)


def _location_keys(cache: RedisCacheService) -> list[str]:
    return sorted(cache._redis.scan_iter("test-cache:nautobot:devices:location:*"))


class BulkRefreshInvalidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cache = _cache()
        self.devices = [_gql("a", "r1"), _gql("b", "r2", location="dc2")]

    async def _prime(self) -> NautobotSourceQueryService:
        """Bulk cache populated, two location filters cached."""
        svc = _service(self.cache, self.devices)
        await svc.refresh_bulk_cache()
        await svc._query_devices_by_location("dc1")
        await svc._query_devices_by_location("dc2")
        self.assertEqual(len(_location_keys(self.cache)), 2)
        return svc

    async def _refresh_with(self, devices: list[dict]) -> int:
        svc = _service(self.cache, devices)
        return await svc.refresh_bulk_cache()

    async def test_unchanged_devices_keep_the_location_entries(self) -> None:
        await self._prime()

        count = await self._refresh_with(list(self.devices))

        self.assertEqual(count, 2)
        self.assertEqual(len(_location_keys(self.cache)), 2)

    async def test_device_order_alone_is_not_a_change(self) -> None:
        await self._prime()

        await self._refresh_with(list(reversed(self.devices)))

        self.assertEqual(len(_location_keys(self.cache)), 2)

    async def test_new_device_invalidates_location_entries(self) -> None:
        await self._prime()

        await self._refresh_with([*self.devices, _gql("c", "r3")])

        self.assertEqual(_location_keys(self.cache), [])

    async def test_removed_device_invalidates_location_entries(self) -> None:
        await self._prime()

        await self._refresh_with(self.devices[:1])

        self.assertEqual(_location_keys(self.cache), [])

    async def test_moved_device_invalidates_location_entries(self) -> None:
        await self._prime()

        await self._refresh_with([_gql("a", "r1", location="dc2"), self.devices[1]])

        self.assertEqual(_location_keys(self.cache), [])

    async def test_changed_device_detail_invalidates_location_entries(self) -> None:
        # Location entries also hold each device's primary IP etc., so a changed
        # primary IP must not keep being served from a stale location entry.
        await self._prime()

        await self._refresh_with([_gql("a", "r1", ip="10.9.9.9/24"), self.devices[1]])

        self.assertEqual(_location_keys(self.cache), [])

    async def test_next_location_query_after_invalidation_sees_the_new_device(self) -> None:
        await self._prime()
        new_devices = [*self.devices, _gql("c", "r3")]
        await self._refresh_with(new_devices)

        fresh = _service(self.cache, new_devices)
        devices = await fresh._query_devices_by_location("dc1")

        fresh._nautobot.graphql_query.assert_awaited_once()
        self.assertEqual({d.id for d in devices}, {"a", "b", "c"})

    async def test_first_refresh_with_no_previous_bulk_entry_invalidates(self) -> None:
        # Bulk entry gone (expiry / Redis flush): we can't tell what changed.
        svc = await self._prime()
        self.cache.delete(svc._bulk_cache_key)

        await self._refresh_with(list(self.devices))

        self.assertEqual(_location_keys(self.cache), [])

    async def test_only_this_nautobot_instances_entries_are_dropped(self) -> None:
        await self._prime()
        other = _service(self.cache, self.devices, creds=_OTHER)
        await other.refresh_bulk_cache()
        await other._query_devices_by_location("dc1")
        self.assertEqual(len(_location_keys(self.cache)), 3)

        await self._refresh_with([*self.devices, _gql("c", "r3")])

        (remaining,) = _location_keys(self.cache)
        self.assertIn(_OTHER.cache_scope, remaining)

    async def test_malformed_previous_entry_is_treated_as_changed(self) -> None:
        svc = await self._prime()
        self.cache.set(svc._bulk_cache_key, [{"no": "id"}, "garbage"], ttl_seconds=60)

        count = await self._refresh_with(list(self.devices))

        self.assertEqual(count, 2)
        self.assertEqual(_location_keys(self.cache), [])

    async def test_the_bulk_entry_is_still_written_when_invalidating(self) -> None:
        svc = await self._prime()

        await self._refresh_with([*self.devices, _gql("c", "r3")])

        self.assertEqual(len(self.cache.get(svc._bulk_cache_key)), 3)

    async def test_unreadable_previous_entry_still_refreshes_and_invalidates(self) -> None:
        svc = await self._prime()
        real_get = self.cache.get

        def flaky_get(key: str):
            if key == svc._bulk_cache_key:
                raise RuntimeError("redis hiccup")
            return real_get(key)

        with patch.object(self.cache, "get", side_effect=flaky_get):
            count = await self._refresh_with(list(self.devices))

        self.assertEqual(count, 2)
        self.assertEqual(_location_keys(self.cache), [])

    async def test_invalidation_failure_never_fails_the_refresh(self) -> None:
        await self._prime()

        with patch.object(self.cache, "clear_namespace", side_effect=RuntimeError("down")):
            count = await self._refresh_with([*self.devices, _gql("c", "r3")])

        self.assertEqual(count, 3)

    async def test_no_cache_service_means_nothing_to_do(self) -> None:
        svc = _service(None, self.devices)  # type: ignore[arg-type]

        self.assertEqual(await svc.refresh_bulk_cache(), 0)


if __name__ == "__main__":
    unittest.main()
