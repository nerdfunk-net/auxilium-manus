"""Unit tests for services/nautobot/resolvers/* against a mocked NautobotService.

No network: ``graphql_query`` / ``rest_request`` are AsyncMocks returning canned
dict payloads shaped like real Nautobot GraphQL / REST responses.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.resolvers.base_resolver import BaseResolver
from services.nautobot.resolvers.device_resolver import DeviceResolver
from services.nautobot.resolvers.metadata_resolver import MetadataResolver
from services.nautobot.resolvers.network_resolver import NetworkResolver

_UUID = "550e8400-e29b-41d4-a716-446655440000"
_UUID2 = "11111111-2222-3333-4444-555555555555"


def _service(graphql=None, rest=None) -> MagicMock:
    svc = MagicMock()
    svc.graphql_query = AsyncMock(return_value=graphql if graphql is not None else {"data": {}})
    svc.rest_request = AsyncMock(return_value=rest if rest is not None else {})
    return svc


class BaseResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_by_field_returns_first_match(self) -> None:
        svc = _service(graphql={"data": {"platforms": [{"id": _UUID}]}})
        resolver = BaseResolver(svc)
        self.assertEqual(await resolver._resolve_by_field("platforms", "name", "ios"), _UUID)

    async def test_resolve_by_field_wraps_bare_string_in_list(self) -> None:
        svc = _service(graphql={"data": {"platforms": [{"id": _UUID}]}})
        await BaseResolver(svc)._resolve_by_field("platforms", "name", "ios")
        _query, variables = svc.graphql_query.call_args.args
        self.assertEqual(variables, {"value": ["ios"]})

    async def test_resolve_by_field_passes_list_value_through(self) -> None:
        svc = _service(graphql={"data": {"platforms": []}})
        await BaseResolver(svc)._resolve_by_field("platforms", "name", ["ios", "nxos"])
        _query, variables = svc.graphql_query.call_args.args
        self.assertEqual(variables, {"value": ["ios", "nxos"]})

    async def test_resolve_by_field_returns_none_on_graphql_errors(self) -> None:
        svc = _service(graphql={"errors": [{"message": "bad"}]})
        self.assertIsNone(await BaseResolver(svc)._resolve_by_field("platforms", "name", "ios"))

    async def test_resolve_by_field_returns_none_when_empty(self) -> None:
        svc = _service(graphql={"data": {"platforms": []}})
        self.assertIsNone(await BaseResolver(svc)._resolve_by_field("platforms", "name", "ios"))

    async def test_resolve_by_field_swallows_exceptions(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertIsNone(await BaseResolver(svc)._resolve_by_field("platforms", "name", "ios"))

    async def test_resolve_by_name_delegates_to_resolve_by_field(self) -> None:
        svc = _service(graphql={"data": {"roles": [{"id": _UUID}]}})
        self.assertEqual(await BaseResolver(svc)._resolve_by_name("roles", "leaf"), _UUID)


class DeviceResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_device_by_name_found(self) -> None:
        svc = _service(graphql={"data": {"devices": [{"id": _UUID, "name": "r1"}]}})
        self.assertEqual(await DeviceResolver(svc).resolve_device_by_name("r1"), _UUID)

    async def test_resolve_device_by_name_graphql_errors(self) -> None:
        svc = _service(graphql={"errors": ["nope"]})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name("r1"))

    async def test_resolve_device_by_name_not_found(self) -> None:
        svc = _service(graphql={"data": {"devices": []}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name("r1"))

    async def test_resolve_device_by_name_exception(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(side_effect=ValueError("x"))
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name("r1"))

    async def test_resolve_device_by_ip_list_form(self) -> None:
        svc = _service(
            graphql={
                "data": {
                    "ip_addresses": [
                        {"id": "ip1", "primary_ip4_for": [{"id": _UUID, "name": "r1"}]}
                    ]
                }
            }
        )
        self.assertEqual(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"), _UUID)

    async def test_resolve_device_by_ip_single_dict_form(self) -> None:
        svc = _service(
            graphql={
                "data": {
                    "ip_addresses": [
                        {"id": "ip1", "primary_ip4_for": {"id": _UUID, "name": "r1"}}
                    ]
                }
            }
        )
        self.assertEqual(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"), _UUID)

    async def test_resolve_device_by_ip_no_ip_object(self) -> None:
        svc = _service(graphql={"data": {"ip_addresses": []}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"))

    async def test_resolve_device_by_ip_not_primary_for_any_device(self) -> None:
        svc = _service(graphql={"data": {"ip_addresses": [{"id": "ip1", "primary_ip4_for": None}]}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"))

    async def test_resolve_device_by_ip_empty_list(self) -> None:
        svc = _service(
            graphql={"data": {"ip_addresses": [{"id": "ip1", "primary_ip4_for": []}]}}
        )
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"))

    async def test_resolve_device_by_ip_graphql_errors(self) -> None:
        svc = _service(graphql={"errors": ["nope"]})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_ip("10.0.0.1"))

    async def test_resolve_device_id_passes_through_valid_uuid(self) -> None:
        svc = _service()
        self.assertEqual(await DeviceResolver(svc).resolve_device_id(device_id=_UUID), _UUID)
        svc.graphql_query.assert_not_called()

    async def test_resolve_device_id_invalid_uuid_falls_back_to_name(self) -> None:
        svc = _service(graphql={"data": {"devices": [{"id": _UUID, "name": "r1"}]}})
        result = await DeviceResolver(svc).resolve_device_id(device_id="bogus", device_name="r1")
        self.assertEqual(result, _UUID)

    async def test_resolve_device_id_contains_strategy(self) -> None:
        svc = _service(graphql={"data": {"devices": [{"id": _UUID, "name": "core-r1"}]}})
        result = await DeviceResolver(svc).resolve_device_id(
            device_name="r1", matching_strategy="contains"
        )
        self.assertEqual(result, _UUID)
        query = svc.graphql_query.call_args.args[0]
        self.assertIn("name__ic", query)

    async def test_resolve_device_id_starts_with_strategy(self) -> None:
        svc = _service(graphql={"data": {"devices": [{"id": _UUID, "name": "r1-core"}]}})
        result = await DeviceResolver(svc).resolve_device_id(
            device_name="r1", matching_strategy="starts_with"
        )
        self.assertEqual(result, _UUID)
        query = svc.graphql_query.call_args.args[0]
        self.assertIn("name__isw", query)

    async def test_resolve_device_id_ip_fallback(self) -> None:
        svc = _service(
            graphql={
                "data": {
                    "devices": [],
                    "ip_addresses": [{"id": "ip1", "primary_ip4_for": [{"id": _UUID}]}],
                }
            }
        )
        result = await DeviceResolver(svc).resolve_device_id(
            device_name="missing", ip_address="10.0.0.1"
        )
        self.assertEqual(result, _UUID)

    async def test_resolve_device_id_returns_none_when_nothing_matches(self) -> None:
        svc = _service(graphql={"data": {"devices": [], "ip_addresses": []}})
        self.assertIsNone(
            await DeviceResolver(svc).resolve_device_id(
                device_name="missing", ip_address="10.0.0.1"
            )
        )

    async def test_resolve_device_by_name_contains_multiple_uses_first(self) -> None:
        svc = _service(
            graphql={"data": {"devices": [{"id": _UUID, "name": "a"}, {"id": _UUID2, "name": "b"}]}}
        )
        self.assertEqual(
            await DeviceResolver(svc).resolve_device_by_name_contains("x"), _UUID
        )

    async def test_resolve_device_by_name_contains_none(self) -> None:
        svc = _service(graphql={"data": {"devices": []}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name_contains("x"))

    async def test_resolve_device_by_name_contains_errors(self) -> None:
        svc = _service(graphql={"errors": ["x"]})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name_contains("x"))

    async def test_resolve_device_by_name_starts_with_none(self) -> None:
        svc = _service(graphql={"data": {"devices": []}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_by_name_starts_with("x"))

    async def test_resolve_device_by_name_starts_with_multiple_uses_first(self) -> None:
        svc = _service(
            graphql={"data": {"devices": [{"id": _UUID, "name": "a"}, {"id": _UUID2, "name": "b"}]}}
        )
        self.assertEqual(
            await DeviceResolver(svc).resolve_device_by_name_starts_with("x"), _UUID
        )

    async def test_resolve_device_type_id_with_manufacturer(self) -> None:
        svc = _service(
            graphql={
                "data": {"device_types": [{"id": _UUID, "manufacturer": {"name": "Cisco"}}]}
            }
        )
        result = await DeviceResolver(svc).resolve_device_type_id("C9300", manufacturer="Cisco")
        self.assertEqual(result, _UUID)
        _query, variables = svc.graphql_query.call_args.args
        self.assertEqual(variables, {"model": ["C9300"], "manufacturer": ["Cisco"]})

    async def test_resolve_device_type_id_without_manufacturer_not_found(self) -> None:
        svc = _service(graphql={"data": {"device_types": []}})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_type_id("C9300"))

    async def test_resolve_device_type_id_errors(self) -> None:
        svc = _service(graphql={"errors": ["x"]})
        self.assertIsNone(await DeviceResolver(svc).resolve_device_type_id("C9300"))

    async def test_get_device_type_display_prefers_display_field(self) -> None:
        svc = _service(rest={"display": "Cisco C9300-48P", "model": "C9300"})
        self.assertEqual(
            await DeviceResolver(svc).get_device_type_display(_UUID), "Cisco C9300-48P"
        )

    async def test_get_device_type_display_falls_back_to_model(self) -> None:
        svc = _service(rest={"model": "C9300"})
        self.assertEqual(await DeviceResolver(svc).get_device_type_display(_UUID), "C9300")

    async def test_get_device_type_display_none_when_empty(self) -> None:
        svc = _service(rest={})
        self.assertIsNone(await DeviceResolver(svc).get_device_type_display(_UUID))

    async def test_get_device_type_display_exception(self) -> None:
        svc = MagicMock()
        svc.rest_request = AsyncMock(side_effect=RuntimeError("x"))
        self.assertIsNone(await DeviceResolver(svc).get_device_type_display(_UUID))

    async def test_find_interface_with_ip_found(self) -> None:
        svc = _service(
            graphql={
                "data": {
                    "devices": [
                        {"id": "d1", "interfaces": [{"id": "if1", "name": "Gi0/0"}]}
                    ]
                }
            }
        )
        self.assertEqual(
            await DeviceResolver(svc).find_interface_with_ip("r1", "10.0.0.1/24"),
            ("if1", "Gi0/0"),
        )

    async def test_find_interface_with_ip_device_missing(self) -> None:
        svc = _service(graphql={"data": {"devices": []}})
        self.assertIsNone(await DeviceResolver(svc).find_interface_with_ip("r1", "10.0.0.1/24"))

    async def test_find_interface_with_ip_no_interfaces(self) -> None:
        svc = _service(graphql={"data": {"devices": [{"id": "d1", "interfaces": []}]}})
        self.assertIsNone(await DeviceResolver(svc).find_interface_with_ip("r1", "10.0.0.1/24"))

    async def test_find_interface_with_ip_errors(self) -> None:
        svc = _service(graphql={"errors": ["x"]})
        self.assertIsNone(await DeviceResolver(svc).find_interface_with_ip("r1", "10.0.0.1/24"))


class MetadataResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_status_id_passes_through_uuid(self) -> None:
        svc = _service()
        self.assertEqual(await MetadataResolver(svc).resolve_status_id(_UUID), _UUID)
        svc.rest_request.assert_not_called()

    async def test_resolve_status_id_matches_name_case_insensitively(self) -> None:
        svc = _service(
            rest={
                "count": 2,
                "results": [{"name": "Planned", "id": "p"}, {"name": "Active", "id": _UUID}],
            }
        )
        self.assertEqual(await MetadataResolver(svc).resolve_status_id("active"), _UUID)

    async def test_resolve_status_id_raises_when_not_found(self) -> None:
        svc = _service(rest={"count": 1, "results": [{"name": "Planned", "id": "p"}]})
        with self.assertRaises(ValueError):
            await MetadataResolver(svc).resolve_status_id("active")

    async def test_resolve_status_id_raises_on_zero_count(self) -> None:
        svc = _service(rest={"count": 0, "results": []})
        with self.assertRaises(ValueError):
            await MetadataResolver(svc).resolve_status_id("active")

    async def test_resolve_role_id_found(self) -> None:
        svc = _service(graphql={"data": {"roles": [{"id": _UUID}]}})
        self.assertEqual(await MetadataResolver(svc).resolve_role_id("leaf"), _UUID)

    async def test_resolve_role_id_errors_and_missing_and_exception(self) -> None:
        self.assertIsNone(
            await MetadataResolver(_service(graphql={"errors": ["x"]})).resolve_role_id("leaf")
        )
        no_roles = _service(graphql={"data": {"roles": []}})
        self.assertIsNone(await MetadataResolver(no_roles).resolve_role_id("leaf"))
        svc = MagicMock()
        svc.graphql_query = AsyncMock(side_effect=RuntimeError("x"))
        self.assertIsNone(await MetadataResolver(svc).resolve_role_id("leaf"))

    async def test_resolve_platform_id_found_and_missing(self) -> None:
        self.assertEqual(
            await MetadataResolver(
                _service(graphql={"data": {"platforms": [{"id": _UUID}]}})
            ).resolve_platform_id("ios"),
            _UUID,
        )
        self.assertIsNone(
            await MetadataResolver(
                _service(graphql={"data": {"platforms": []}})
            ).resolve_platform_id("ios")
        )

    async def test_get_platform_name(self) -> None:
        self.assertEqual(
            await MetadataResolver(_service(rest={"name": "ios"})).get_platform_name(_UUID), "ios"
        )
        self.assertIsNone(
            await MetadataResolver(_service(rest={})).get_platform_name(_UUID)
        )

    async def test_resolve_location_id_found_and_errors(self) -> None:
        self.assertEqual(
            await MetadataResolver(
                _service(graphql={"data": {"locations": [{"id": _UUID}]}})
            ).resolve_location_id("dc1"),
            _UUID,
        )
        self.assertIsNone(
            await MetadataResolver(_service(graphql={"errors": ["x"]})).resolve_location_id("dc1")
        )

    async def test_resolve_secrets_group_id_found_and_missing(self) -> None:
        self.assertEqual(
            await MetadataResolver(
                _service(graphql={"data": {"secrets_groups": [{"id": _UUID}]}})
            ).resolve_secrets_group_id("grp"),
            _UUID,
        )
        self.assertIsNone(
            await MetadataResolver(
                _service(graphql={"data": {"secrets_groups": []}})
            ).resolve_secrets_group_id("grp")
        )

    async def test_resolve_rack_id_passthrough_uuid(self) -> None:
        svc = _service()
        self.assertEqual(await MetadataResolver(svc).resolve_rack_id(_UUID), _UUID)
        svc.rest_request.assert_not_called()

    async def test_resolve_rack_id_found(self) -> None:
        svc = _service(rest={"count": 1, "results": [{"id": _UUID}]})
        self.assertEqual(await MetadataResolver(svc).resolve_rack_id("A1", location="dc1"), _UUID)
        endpoint = svc.rest_request.call_args.kwargs["endpoint"]
        self.assertIn("location=dc1", endpoint)

    async def test_resolve_rack_id_not_found(self) -> None:
        svc = _service(rest={"count": 0})
        self.assertIsNone(await MetadataResolver(svc).resolve_rack_id("A1"))

    async def test_resolve_rack_id_ambiguous_raises(self) -> None:
        svc = _service(rest={"count": 2, "results": [{"id": "a"}, {"id": "b"}]})
        with self.assertRaises(ValueError):
            await MetadataResolver(svc).resolve_rack_id("A1", location="dc1")

    async def test_resolve_rack_id_swallows_non_value_errors(self) -> None:
        svc = MagicMock()
        svc.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertIsNone(await MetadataResolver(svc).resolve_rack_id("A1"))


class NetworkResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_namespace_id_passthrough_uuid(self) -> None:
        svc = _service()
        self.assertEqual(await NetworkResolver(svc).resolve_namespace_id(_UUID), _UUID)
        svc.graphql_query.assert_not_called()

    async def test_resolve_namespace_id_found(self) -> None:
        svc = _service(graphql={"data": {"namespaces": [{"id": _UUID}]}})
        self.assertEqual(await NetworkResolver(svc).resolve_namespace_id("Global"), _UUID)

    async def test_resolve_namespace_id_raises_on_errors(self) -> None:
        svc = _service(graphql={"errors": ["x"]})
        with self.assertRaises(ValueError):
            await NetworkResolver(svc).resolve_namespace_id("Global")

    async def test_resolve_namespace_id_raises_when_missing(self) -> None:
        svc = _service(graphql={"data": {"namespaces": []}})
        with self.assertRaises(ValueError):
            await NetworkResolver(svc).resolve_namespace_id("Global")

    async def test_resolve_ip_address_found_and_missing(self) -> None:
        self.assertEqual(
            await NetworkResolver(
                _service(graphql={"data": {"ip_addresses": [{"id": _UUID}]}})
            ).resolve_ip_address("10.0.0.1/24", "ns"),
            _UUID,
        )
        self.assertIsNone(
            await NetworkResolver(
                _service(graphql={"data": {"ip_addresses": []}})
            ).resolve_ip_address("10.0.0.1/24", "ns")
        )

    async def test_resolve_ip_address_errors(self) -> None:
        self.assertIsNone(
            await NetworkResolver(_service(graphql={"errors": ["x"]})).resolve_ip_address(
                "10.0.0.1/24", "ns"
            )
        )

    async def test_resolve_interface_by_name_found_and_missing(self) -> None:
        self.assertEqual(
            await NetworkResolver(
                _service(graphql={"data": {"interfaces": [{"id": _UUID}]}})
            ).resolve_interface_by_name("d1", "Gi0/0"),
            _UUID,
        )
        self.assertIsNone(
            await NetworkResolver(
                _service(graphql={"data": {"interfaces": []}})
            ).resolve_interface_by_name("d1", "Gi0/0")
        )

    async def test_resolve_prefix_found_missing_and_exception(self) -> None:
        self.assertEqual(
            await NetworkResolver(
                _service(rest={"count": 1, "results": [{"id": _UUID}]})
            ).resolve_prefix("10.0.0.0/24", "ns"),
            _UUID,
        )
        self.assertIsNone(
            await NetworkResolver(_service(rest={"count": 0})).resolve_prefix("10.0.0.0/24", "ns")
        )
        svc = MagicMock()
        svc.rest_request = AsyncMock(side_effect=RuntimeError("x"))
        self.assertIsNone(await NetworkResolver(svc).resolve_prefix("10.0.0.0/24", "ns"))


if __name__ == "__main__":
    unittest.main()
