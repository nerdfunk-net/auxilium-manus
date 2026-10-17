"""Unit tests for services/nautobot/devices/query.py and attribute_bag.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.attribute_bag import (
    attributes_from_detail,
    build_attribute_variables,
    normalize_attribute_groups,
)
from services.nautobot.devices.query import DeviceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


class AttributeBagTests(unittest.TestCase):
    def test_normalize_attribute_groups_filters_and_preserves_order(self) -> None:
        self.assertEqual(normalize_attribute_groups(None), [])
        self.assertEqual(
            normalize_attribute_groups(["tags", "bogus", "interfaces"]),
            ["tags", "interfaces"],
        )

    def test_build_attribute_variables_always_requests_primary_ip(self) -> None:
        self.assertEqual(build_attribute_variables(None), {"get_primary_ipv4": True})

    def test_build_attribute_variables_toggles_known_groups(self) -> None:
        variables = build_attribute_variables(["interfaces", "tags"])
        self.assertTrue(variables["get_primary_ipv4"])
        self.assertTrue(variables["get_interfaces"])
        self.assertTrue(variables["get_tags"])

    def test_attributes_from_detail_renames_custom_field_data(self) -> None:
        bag = attributes_from_detail({"name": "r1", "_custom_field_data": {"site": "NYC"}})
        self.assertEqual(bag, {"name": "r1", "custom_fields": {"site": "NYC"}})

    def test_attributes_from_detail_without_custom_fields(self) -> None:
        self.assertEqual(attributes_from_detail({"name": "r1"}), {"name": "r1"})


def _service(graphql_result: dict, cache: MagicMock | None = None) -> DeviceQueryService:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value=graphql_result)
    return DeviceQueryService(nautobot, _CREDS, cache_service=cache)


class DeviceQueryServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_cache_key_shapes(self) -> None:
        svc = _service({})
        self.assertTrue(svc._details_cache_key("d1").startswith("nautobot:device_details:"))
        key = svc._attributes_cache_key("d1", ["tags", "interfaces"])
        self.assertTrue(key.endswith("interfaces,tags"))
        self.assertTrue(svc._attributes_cache_key("d1", []).endswith(":base"))

    async def test_get_device_attributes_returns_cached_value(self) -> None:
        cache = MagicMock()
        cache.get.return_value = {"name": "cached"}
        svc = _service({"data": {"device": {"name": "fresh"}}}, cache=cache)
        result = await svc.get_device_attributes("d1")
        self.assertEqual(result, {"name": "cached"})
        svc._nautobot.graphql_query.assert_not_called()

    async def test_get_device_attributes_queries_and_caches_on_miss(self) -> None:
        cache = MagicMock()
        cache.get.return_value = None
        svc = _service(
            {"data": {"device": {"name": "r1", "_custom_field_data": {"a": 1}}}}, cache=cache
        )
        result = await svc.get_device_attributes("d1", ["tags"])
        self.assertEqual(result["custom_fields"], {"a": 1})
        cache.set.assert_called_once()

    async def test_get_device_attributes_skips_cache_when_disabled(self) -> None:
        cache = MagicMock()
        cache.get.return_value = {"name": "cached"}
        svc = _service({"data": {"device": {"name": "r1"}}}, cache=cache)
        result = await svc.get_device_attributes("d1", use_cache=False)
        self.assertEqual(result["name"], "r1")
        cache.get.assert_not_called()

    async def test_get_device_attributes_raises_on_graphql_errors(self) -> None:
        svc = _service({"errors": [{"message": "bad"}]})
        with self.assertRaises(ValueError):
            await svc.get_device_attributes("d1")

    async def test_get_device_attributes_raises_when_device_missing(self) -> None:
        svc = _service({"data": {"device": None}})
        with self.assertRaises(ValueError):
            await svc.get_device_attributes("d1")

    async def test_get_device_details_cache_hit(self) -> None:
        cache = MagicMock()
        cache.get.return_value = {"id": "d1"}
        svc = _service({"data": {"device": {"id": "other"}}}, cache=cache)
        self.assertEqual(await svc.get_device_details("d1"), {"id": "d1"})

    async def test_get_device_details_queries_and_caches(self) -> None:
        cache = MagicMock()
        cache.get.return_value = None
        svc = _service({"data": {"device": {"id": "d1", "name": "r1"}}}, cache=cache)
        result = await svc.get_device_details("d1")
        self.assertEqual(result["name"], "r1")
        cache.set.assert_called_once()

    async def test_get_device_details_raises_on_errors_and_missing(self) -> None:
        with self.assertRaises(ValueError):
            await _service({"errors": ["x"]}).get_device_details("d1")
        with self.assertRaises(ValueError):
            await _service({"data": {}}).get_device_details("d1")


if __name__ == "__main__":
    unittest.main()
