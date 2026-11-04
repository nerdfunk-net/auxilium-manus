"""Unit tests for services/nautobot/devices/query.py and attribute_bag.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.attribute_bag import (
    CABLES_LAYOUT_LEGACY,
    CABLES_LAYOUT_V32,
    DEVICE_ATTRIBUTES_QUERY,
    attributes_from_detail,
    build_attribute_variables,
    build_device_attributes_query,
    cables_layout_for_version,
    device_query_for_groups,
    normalize_attribute_groups,
)
from services.nautobot.devices.query import DeviceQueryService
from services.nautobot.version import parse_nautobot_version

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

    def test_cables_group_is_recognised_and_toggles_variable(self) -> None:
        self.assertEqual(normalize_attribute_groups(["cables", "bogus"]), ["cables"])
        self.assertTrue(build_attribute_variables(["cables"])["get_cables"])
        self.assertNotIn("get_cables", build_attribute_variables(["interfaces"]))

    def test_base_query_has_no_cable_selection(self) -> None:
        # GraphQL validates skipped fields too: nothing 3.2-only may be in the base query.
        self.assertNotIn("get_cables", DEVICE_ATTRIBUTES_QUERY)
        self.assertNotIn("cable", DEVICE_ATTRIBUTES_QUERY)
        self.assertNotIn("connected_", DEVICE_ATTRIBUTES_QUERY)

    def test_legacy_cables_query_avoids_cabletype_interfaces(self) -> None:
        query = build_device_attributes_query(CABLES_LAYOUT_LEGACY)
        self.assertIn("$get_cables: Boolean = false", query)
        selection = query.split("interfaces @include(if: $get_cables)", 1)[1]
        self.assertIn("connected_endpoint", selection)
        for field in ("type", "tags", "status"):
            self.assertIn(field, selection)
        # no ``interfaces`` nested inside ``cable``
        self.assertNotIn("interfaces", selection)

    def test_v32_cables_query_selects_cable_interfaces(self) -> None:
        query = build_device_attributes_query(CABLES_LAYOUT_V32)
        self.assertIn("$get_cables: Boolean = false", query)
        selection = query.split("interfaces @include(if: $get_cables)", 1)[1]
        for field in ("label", "type", "tags", "status", "device", "interfaces"):
            self.assertIn(field, selection)

    def test_layout_follows_version(self) -> None:
        self.assertEqual(cables_layout_for_version((3, 1)), CABLES_LAYOUT_LEGACY)
        self.assertEqual(cables_layout_for_version((3, 0)), CABLES_LAYOUT_LEGACY)
        self.assertEqual(cables_layout_for_version(None), CABLES_LAYOUT_LEGACY)
        self.assertEqual(cables_layout_for_version((3, 2)), CABLES_LAYOUT_V32)
        self.assertEqual(cables_layout_for_version((4, 0)), CABLES_LAYOUT_V32)

    def test_parse_nautobot_version(self) -> None:
        self.assertEqual(parse_nautobot_version("3.1.1"), (3, 1))
        self.assertEqual(parse_nautobot_version("v3.2.0b1"), (3, 2))
        self.assertIsNone(parse_nautobot_version("garbage"))
        self.assertIsNone(parse_nautobot_version(None))


class DeviceQueryForGroupsTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_cables_no_version_lookup(self) -> None:
        service = MagicMock()
        service.test_connection = AsyncMock()
        query = await device_query_for_groups(service, MagicMock(), ["interfaces"])
        self.assertEqual(query, DEVICE_ATTRIBUTES_QUERY)
        service.test_connection.assert_not_called()

    async def test_cables_picks_layout_from_server_version(self) -> None:
        for version, layout in (("3.1.1", CABLES_LAYOUT_LEGACY), ("3.2.0", CABLES_LAYOUT_V32)):
            service = MagicMock()
            service.test_connection = AsyncMock(return_value={"nautobot-version": version})
            credentials = MagicMock(url="http://nb.example")
            query = await device_query_for_groups(service, credentials, ["cables"])
            self.assertEqual(query, build_device_attributes_query(layout))

    async def test_version_lookup_failure_falls_back_to_legacy(self) -> None:
        service = MagicMock()
        service.test_connection = AsyncMock(side_effect=RuntimeError("down"))
        query = await device_query_for_groups(
            service, MagicMock(url="http://nb.example"), ["cables"]
        )
        self.assertEqual(query, build_device_attributes_query(CABLES_LAYOUT_LEGACY))


class AttributeBagMoreTests(unittest.TestCase):
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


class PreviewNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_normalizes_cables_and_keys_cache_by_layout(self) -> None:
        legacy_device = {
            "id": "d1",
            "name": "lab",
            "interfaces": [
                {
                    "id": "i1",
                    "name": "e0",
                    "cable": {"id": "c1"},
                    "connected_endpoint": {
                        "__typename": "InterfaceType",
                        "id": "i2",
                        "name": "e1",
                        "device": {"id": "d2", "name": "sw"},
                    },
                }
            ],
        }
        nautobot = MagicMock()
        nautobot.test_connection = AsyncMock(return_value={"nautobot-version": "3.1.1"})
        nautobot.graphql_query = AsyncMock(return_value={"data": {"device": legacy_device}})
        cache = MagicMock()
        cache.get.return_value = None
        svc = DeviceQueryService(nautobot, _CREDS, cache_service=cache)
        out = await svc.get_device_attributes("d1", ["cables"])
        self.assertEqual(out["interfaces"][0]["cable"]["far_end"]["name"], "e1")
        self.assertTrue(cache.set.call_args.args[0].endswith(":cables:legacy"))

    async def test_without_cables_nothing_is_normalized(self) -> None:
        device = {"id": "d1", "interfaces": [{"id": "i", "cable": {}}]}
        nautobot = MagicMock()
        nautobot.test_connection = AsyncMock()
        nautobot.graphql_query = AsyncMock(return_value={"data": {"device": device}})
        svc = DeviceQueryService(nautobot, _CREDS)
        out = await svc.get_device_attributes("d1", ["interfaces"], use_cache=False)
        self.assertNotIn("far_end", out["interfaces"][0]["cable"])
        nautobot.test_connection.assert_not_called()
