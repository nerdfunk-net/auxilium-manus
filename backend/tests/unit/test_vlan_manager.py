"""Unit tests for services/nautobot/managers/vlan_manager.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.managers.vlan_manager import VLANManager

_DEFAULT_REST_RESULT = {"id": "new-vlan-uuid"}


def _make_manager(*, graphql_results=None, rest_result=_DEFAULT_REST_RESULT) -> VLANManager:
    nautobot = MagicMock()
    if graphql_results is not None:
        nautobot.graphql_query = AsyncMock(side_effect=graphql_results)
    else:
        nautobot.graphql_query = AsyncMock(return_value={"data": {"vlans": []}})
    nautobot.rest_request = AsyncMock(return_value=rest_result)
    metadata_resolver = MagicMock()
    metadata_resolver.resolve_status_id = AsyncMock(return_value="status-uuid")
    manager = VLANManager(nautobot, metadata_resolver)
    return manager


class ResolveVlanIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_location_scoped_match_returns_first_result(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": [{"id": "v1", "name": "vlan-100"}]}},
            ]
        )
        result = await manager.resolve_vlan_id(100, location_id="loc-uuid")
        self.assertEqual(result, "v1")
        manager.nautobot.graphql_query.assert_awaited_once()
        variables = manager.nautobot.graphql_query.call_args.args[1]
        self.assertEqual(variables, {"vid": [100], "location": ["loc-uuid"]})

    async def test_empty_location_scoped_falls_back_to_vid_only(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": []}},
                {"data": {"vlans": [{"id": "v2", "name": "vlan-100"}]}},
            ]
        )
        result = await manager.resolve_vlan_id(100, location_id="loc-uuid")
        self.assertEqual(result, "v2")
        self.assertEqual(manager.nautobot.graphql_query.await_count, 2)
        second_call_variables = manager.nautobot.graphql_query.call_args.args[1]
        self.assertEqual(second_call_variables, {"vid": [100]})

    async def test_multiple_results_takes_first(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {
                    "data": {
                        "vlans": [
                            {"id": "v1", "name": "vlan-100"},
                            {"id": "v2", "name": "vlan-100"},
                        ]
                    }
                },
            ]
        )
        result = await manager.resolve_vlan_id(100)
        self.assertEqual(result, "v1")

    async def test_no_location_queries_vid_only_directly(self) -> None:
        manager = _make_manager(graphql_results=[{"data": {"vlans": []}}])
        result = await manager.resolve_vlan_id(100)
        self.assertIsNone(result)
        manager.nautobot.graphql_query.assert_awaited_once()

    async def test_no_matches_anywhere_returns_none(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": []}},
                {"data": {"vlans": []}},
            ]
        )
        result = await manager.resolve_vlan_id(100, location_id="loc-uuid")
        self.assertIsNone(result)

    async def test_graphql_errors_raise(self) -> None:
        manager = _make_manager(graphql_results=[{"errors": [{"message": "boom"}]}])
        with self.assertRaises(NautobotAPIError):
            await manager.resolve_vlan_id(100)


class EnsureVlanExistsTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_vlan_found_skips_creation(self) -> None:
        manager = _make_manager(
            graphql_results=[{"data": {"vlans": [{"id": "existing", "name": "vlan-100"}]}}]
        )
        result = await manager.ensure_vlan_exists(100, location_id="loc-uuid")
        self.assertEqual(result, "existing")
        manager.nautobot.rest_request.assert_not_awaited()

    async def test_not_found_creates_with_default_name_and_location(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": []}},
                {"data": {"vlans": []}},
            ],
            rest_result={"id": "created-uuid"},
        )
        result = await manager.ensure_vlan_exists(100, location_id="loc-uuid")
        self.assertEqual(result, "created-uuid")
        manager.metadata_resolver.resolve_status_id.assert_awaited_once_with(
            "active", content_type="ipam.vlan"
        )
        manager.nautobot.rest_request.assert_awaited_once_with(
            endpoint="ipam/vlans/",
            method="POST",
            data={
                "vid": 100,
                "name": "vlan-100",
                "status": "status-uuid",
                "locations": ["loc-uuid"],
            },
        )

    async def test_not_found_no_location_omits_locations_field(self) -> None:
        manager = _make_manager(graphql_results=[{"data": {"vlans": []}}])
        await manager.ensure_vlan_exists(100)
        _args, kwargs = manager.nautobot.rest_request.call_args
        self.assertNotIn("locations", kwargs["data"])

    async def test_custom_name_and_status_used(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": []}},
                {"data": {"vlans": []}},
            ]
        )
        await manager.ensure_vlan_exists(100, name="custom-vlan", status="planned")
        manager.metadata_resolver.resolve_status_id.assert_awaited_once_with(
            "planned", content_type="ipam.vlan"
        )
        _args, kwargs = manager.nautobot.rest_request.call_args
        self.assertEqual(kwargs["data"]["name"], "custom-vlan")

    async def test_missing_id_in_create_response_raises(self) -> None:
        manager = _make_manager(
            graphql_results=[
                {"data": {"vlans": []}},
                {"data": {"vlans": []}},
            ],
            rest_result={},
        )
        with self.assertRaises(NautobotAPIError):
            await manager.ensure_vlan_exists(100)


if __name__ == "__main__":
    unittest.main()
