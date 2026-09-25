"""Tests for services/sources/nautobot/query_service.py + live_query_mixin.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.live_query_mixin import _resolve_location_filter_arg
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


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


class LiveQueryPureHelperTests(unittest.TestCase):
    def test_resolve_location_filter_arg(self) -> None:
        self.assertEqual(_resolve_location_filter_arg(False, True), "location__n: $location_filter")
        self.assertIn("__name__ic", _resolve_location_filter_arg(True, False))
        self.assertEqual(_resolve_location_filter_arg(False, False), "location: $location_filter")


def _service(graphql=None, cache=None) -> NautobotSourceQueryService:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value=graphql or {"data": {"devices": []}})
    return NautobotSourceQueryService(nautobot, _CREDS, cache, bulk_ttl=60)


class ParseTests(unittest.TestCase):
    def test_parse_device_from_cache(self) -> None:
        dev = _service()._parse_device_from_cache(
            {
                "id": "a",
                "name": "r1",
                "tags": ["x"],
                "manufacturer": "Cisco",
                "custom_fields": {"site_code": "NYC"},
            }
        )
        self.assertEqual(dev.id, "a")
        self.assertEqual(dev.tags, ["x"])
        self.assertEqual(dev.custom_fields, {"site_code": "NYC"})

    def test_parse_device_from_cache_defaults_missing_custom_fields(self) -> None:
        dev = _service()._parse_device_from_cache({"id": "a", "name": "r1"})
        self.assertEqual(dev.custom_fields, {})

    def test_parse_device_data_full_and_minimal(self) -> None:
        parsed = _service()._parse_device_data([_gql_device("a", "r1"), {"id": "b"}])
        self.assertEqual(parsed[0].manufacturer, "Cisco")
        self.assertEqual(parsed[0].platform_network_driver, "ios")
        self.assertEqual(parsed[0].custom_fields, {"site_code": "NYC"})
        self.assertEqual(parsed[1].id, "b")
        self.assertIsNone(parsed[1].status)
        self.assertEqual(parsed[1].custom_fields, {})


class CachedDeviceListTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hit_parses_and_memoises(self) -> None:
        cache = MagicMock()
        cache.get.return_value = [{"id": "a", "name": "r1"}]
        svc = _service(cache=cache)
        first = await svc._get_all_devices_cached()
        second = await svc._get_all_devices_cached()
        self.assertEqual(first[0].id, "a")
        self.assertIs(first, second)
        cache.get.assert_called_once()

    async def test_cache_miss_falls_back_to_live(self) -> None:
        cache = MagicMock()
        cache.get.return_value = None
        svc = _service(graphql={"data": {"devices": [_gql_device("a", "r1")]}}, cache=cache)
        devices = await svc._get_all_devices_cached()
        self.assertEqual(devices[0].id, "a")

    async def test_redis_error_falls_back_to_live(self) -> None:
        cache = MagicMock()
        cache.get.side_effect = RuntimeError("redis down")
        svc = _service(graphql={"data": {"devices": [_gql_device("a", "r1")]}}, cache=cache)
        devices = await svc._get_all_devices_cached()
        self.assertEqual(len(devices), 1)

    async def test_refresh_bulk_cache_without_cache_returns_zero(self) -> None:
        self.assertEqual(await _service().refresh_bulk_cache(), 0)

    async def test_refresh_bulk_cache_writes_payload(self) -> None:
        cache = MagicMock()
        svc = _service(graphql={"data": {"devices": [_gql_device("a", "r1")]}}, cache=cache)
        count = await svc.refresh_bulk_cache()
        self.assertEqual(count, 1)
        cache.set.assert_called_once()


class CacheFilterMethodTests(unittest.IsolatedAsyncioTestCase):
    def _svc_with_devices(self, devices: list[dict]) -> NautobotSourceQueryService:
        cache = MagicMock()
        cache.get.return_value = devices
        return _service(cache=cache)

    async def test_by_name_exact_and_contains_and_empty(self) -> None:
        svc = self._svc_with_devices(
            [{"id": "a", "name": "core-rtr"}, {"id": "b", "name": "edge-rtr"}]
        )
        self.assertEqual(await svc._query_devices_by_name(""), [])
        exact = await svc._query_devices_by_name("core-rtr")
        self.assertEqual([d.id for d in exact], ["a"])
        contains = await svc._query_devices_by_name("rtr", use_contains=True)
        self.assertEqual({d.id for d in contains}, {"a", "b"})

    async def test_by_role_match_and_negation(self) -> None:
        svc = self._svc_with_devices(
            [{"id": "a", "name": "x", "role": "leaf"}, {"id": "b", "name": "y", "role": "spine"}]
        )
        self.assertEqual([d.id for d in await svc._query_devices_by_role("leaf")], ["a"])
        self.assertEqual(
            [d.id for d in await svc._query_devices_by_role("leaf", use_negation=True)], ["b"]
        )
        self.assertEqual(await svc._query_devices_by_role(""), [])

    async def test_by_status_tag_platform_has_primary(self) -> None:
        svc = self._svc_with_devices(
            [
                {"id": "a", "name": "x", "status": "Active", "tags": ["t1"],
                 "platform": "ios", "primary_ip4": "10.0.0.1/24"},
                {"id": "b", "name": "y", "status": "Planned", "tags": [], "platform": "eos"},
            ]
        )
        self.assertEqual([d.id for d in await svc._query_devices_by_status("Active")], ["a"])
        self.assertEqual([d.id for d in await svc._query_devices_by_tag("t1")], ["a"])
        self.assertEqual([d.id for d in await svc._query_devices_by_platform("eos")], ["b"])
        self.assertEqual([d.id for d in await svc._query_devices_by_has_primary("true")], ["a"])
        self.assertEqual([d.id for d in await svc._query_devices_by_has_primary("false")], ["b"])

    async def test_by_devicetype_and_manufacturer_negation(self) -> None:
        svc = self._svc_with_devices(
            [
                {"id": "a", "name": "x", "device_type": "C9300", "manufacturer": "Cisco"},
                {"id": "b", "name": "y", "device_type": "QFX", "manufacturer": "Juniper"},
            ]
        )
        self.assertEqual([d.id for d in await svc._query_devices_by_devicetype("C9300")], ["a"])
        self.assertEqual(
            [d.id for d in await svc._query_devices_by_devicetype("C9300", use_negation=True)],
            ["b"],
        )
        self.assertEqual(
            [d.id for d in await svc._query_devices_by_manufacturer("Juniper")], ["b"]
        )
        self.assertEqual(await svc._query_devices_by_manufacturer(""), [])

    async def test_by_custom_field_exact_contains_multiselect_and_empty(self) -> None:
        svc = self._svc_with_devices(
            [
                {"id": "a", "name": "x", "custom_fields": {"site_code": "NYC-01"}},
                {"id": "b", "name": "y", "custom_fields": {"site_code": "LAX-01"}},
                {"id": "c", "name": "z", "custom_fields": {"site_code": ["NYC-01", "BOS-01"]}},
                {"id": "d", "name": "w", "custom_fields": {}},
            ]
        )
        self.assertEqual(
            [d.id for d in await svc._query_devices_by_custom_field("cf_site_code", "NYC-01")],
            ["a", "c"],
        )
        self.assertEqual(
            [
                d.id
                for d in await svc._query_devices_by_custom_field(
                    "cf_site_code", "nyc", use_contains=True
                )
            ],
            ["a", "c"],
        )
        self.assertEqual(await svc._query_devices_by_custom_field("cf_site_code", ""), [])
        self.assertEqual(await svc._query_devices_by_custom_field("", "NYC-01"), [])


class LiveQueryMixinMethodTests(unittest.IsolatedAsyncioTestCase):
    async def test_location_query_empty_and_parsed(self) -> None:
        svc = _service(graphql={"data": {"devices": [_gql_device("a", "r1")]}})
        self.assertEqual(await svc._query_devices_by_location(""), [])
        devices = await svc._query_devices_by_location("dc1")
        self.assertEqual(devices[0].id, "a")

    async def test_ip_prefix_query_dedups_devices(self) -> None:
        dev = _gql_device("a", "r1")
        payload = {
            "data": {
                "prefixes": [
                    {
                        "ip_addresses": [
                            {"interface_assignments": [{"interface": {"device": dev}}]},
                            {"interface_assignments": [{"interface": {"device": dev}}]},
                        ]
                    }
                ]
            }
        }
        svc = _service(graphql=payload)
        devices = await svc._query_devices_by_ip_prefix("10.0.0.0/24 Global")
        self.assertEqual([d.id for d in devices], ["a"])

    async def test_ip_prefix_query_errors_return_empty(self) -> None:
        svc = _service(graphql={"errors": [{"message": "bad"}]})
        self.assertEqual(await svc._query_devices_by_ip_prefix("10.0.0.0/24"), [])

    async def test_primary_prefix_query(self) -> None:
        dev = _gql_device("a", "r1")
        payload = {"data": {"ip_addresses": [{"address": "10.0.0.1/24", "primary_ip4_for": [dev]}]}}
        svc = _service(graphql=payload)
        devices = await svc._query_devices_by_primary_prefix("10.0.0.0/24")
        self.assertEqual([d.id for d in devices], ["a"])


if __name__ == "__main__":
    unittest.main()
