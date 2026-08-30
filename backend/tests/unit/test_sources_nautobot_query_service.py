"""Tests for services/sources/nautobot/query_service.py + live_query_mixin.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.live_query_mixin import (
    _build_custom_field_devices_query,
    _custom_field_graphql_var_type,
    _custom_field_query_variables,
    _resolve_location_filter_arg,
)
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


def _gql_device(did: str, name: str, **over) -> dict:
    d = {
        "id": did,
        "name": name,
        "serial": "SN",
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

    def test_custom_field_graphql_var_type(self) -> None:
        self.assertEqual(_custom_field_graphql_var_type("select", False), "[String]")
        self.assertEqual(_custom_field_graphql_var_type("text", True), "[String]")
        self.assertEqual(_custom_field_graphql_var_type("text", False), "String")

    def test_build_custom_field_devices_query(self) -> None:
        contains_q = _build_custom_field_devices_query("cf_site", "[String]", use_contains=True)
        self.assertIn("cf_site__ic: $field_value", contains_q)
        exact_q = _build_custom_field_devices_query("cf_site", "String", use_contains=False)
        self.assertIn("cf_site: $field_value", exact_q)

    def test_custom_field_query_variables(self) -> None:
        self.assertEqual(_custom_field_query_variables("[String]", "x"), {"field_value": ["x"]})
        self.assertEqual(_custom_field_query_variables("String", "x"), {"field_value": "x"})


def _service(graphql=None, cache=None) -> NautobotSourceQueryService:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value=graphql or {"data": {"devices": []}})
    return NautobotSourceQueryService(nautobot, _CREDS, cache, bulk_ttl=60)


class ParseTests(unittest.TestCase):
    def test_parse_device_from_cache(self) -> None:
        dev = _service()._parse_device_from_cache(
            {"id": "a", "name": "r1", "tags": ["x"], "manufacturer": "Cisco"}
        )
        self.assertEqual(dev.id, "a")
        self.assertEqual(dev.tags, ["x"])

    def test_parse_device_data_full_and_minimal(self) -> None:
        parsed = _service()._parse_device_data([_gql_device("a", "r1"), {"id": "b"}])
        self.assertEqual(parsed[0].manufacturer, "Cisco")
        self.assertEqual(parsed[0].platform_network_driver, "ios")
        self.assertEqual(parsed[1].id, "b")
        self.assertIsNone(parsed[1].status)


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


class CustomFieldTypesTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_and_caches_types(self) -> None:
        svc = _service()
        with patch(
            "services.nautobot.metadata_service.NautobotMetadataService"
        ) as meta_cls:
            meta_cls.return_value.get_device_custom_fields = AsyncMock(
                return_value=[{"key": "site", "type": {"value": "select"}}]
            )
            types = await svc._get_custom_field_types()
        self.assertEqual(types, {"site": "select"})
        # cached: second call does not re-instantiate
        self.assertEqual(await svc._get_custom_field_types(), {"site": "select"})

    async def test_error_returns_empty_mapping(self) -> None:
        svc = _service()
        with patch(
            "services.nautobot.metadata_service.NautobotMetadataService",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(await svc._get_custom_field_types(), {})


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

    async def test_custom_field_query_empty_and_select(self) -> None:
        svc = _service(graphql={"data": {"devices": [_gql_device("a", "r1")]}})
        self.assertEqual(await svc._query_devices_by_custom_field("cf_site", ""), [])
        with patch.object(
            svc, "_get_custom_field_types", AsyncMock(return_value={"site": "select"})
        ):
            devices = await svc._query_devices_by_custom_field("cf_site", "NYC")
        self.assertEqual(devices[0].id, "a")

    async def test_custom_field_query_graphql_errors(self) -> None:
        svc = _service(graphql={"errors": ["boom"]})
        with patch.object(svc, "_get_custom_field_types", AsyncMock(return_value={})):
            self.assertEqual(await svc._query_devices_by_custom_field("cf_site", "NYC"), [])


if __name__ == "__main__":
    unittest.main()
