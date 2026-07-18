"""Tests for ISENetworkDeviceGroupService (mocked ISEService, no real network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from services.ise.common.exceptions import ISENotFoundError, ISEValidationError
from services.ise.credentials import ISECredentials
from services.ise.network_device_group_service import ISENetworkDeviceGroupService


def _credentials() -> ISECredentials:
    return ISECredentials(base_url="https://10.10.20.77", username="admin", password="secret")


class ISENetworkDeviceGroupServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ise = AsyncMock()
        self.service = ISENetworkDeviceGroupService(self.ise, _credentials())

    async def test_list_groups_passes_pagination_and_filter(self) -> None:
        self.ise.ers_request.return_value = {"SearchResult": {"total": 0, "resources": []}}
        await self.service.list_groups(page=2, size=50, filter_="name.CONTAINS.Building")
        self.ise.ers_request.assert_called_once_with(
            "networkdevicegroup",
            _credentials(),
            method="GET",
            params={"page": 2, "size": 50, "filter": "name.CONTAINS.Building"},
        )

    async def test_list_groups_without_filter_omits_param(self) -> None:
        self.ise.ers_request.return_value = {"SearchResult": {"total": 0, "resources": []}}
        await self.service.list_groups()
        self.ise.ers_request.assert_called_once_with(
            "networkdevicegroup",
            _credentials(),
            method="GET",
            params={"page": 1, "size": 20},
        )

    async def test_get_group_by_name_returns_none_on_404(self) -> None:
        self.ise.ers_request.side_effect = ISENotFoundError("not found")
        result = await self.service.get_group_by_name("Location#Missing")
        self.assertIsNone(result)

    async def test_get_group_by_name_url_encodes_hash_and_spaces(self) -> None:
        self.ise.ers_request.return_value = {"NetworkDeviceGroup": {}}
        await self.service.get_group_by_name("Location#All Locations")
        endpoint = self.ise.ers_request.call_args.args[0]
        self.assertEqual(endpoint, "networkdevicegroup/name/Location%23All%20Locations")

    async def test_create_location_raises_when_parent_missing(self) -> None:
        self.ise.ers_request.side_effect = ISENotFoundError("not found")
        with self.assertRaises(ISEValidationError) as ctx:
            await self.service.create_location(
                name="Building1", description="test", parent_group="Nonexistent"
            )
        self.assertIn("Nonexistent", str(ctx.exception))

    async def test_create_location_builds_hierarchical_name(self) -> None:
        self.ise.ers_request.side_effect = [
            {"NetworkDeviceGroup": {"name": "Location#All Locations", "othername": "Location"}},
            {"id": "new-group-id"},
        ]

        result = await self.service.create_location(
            name="Building1", description="HQ building", parent_group="All Locations"
        )

        self.assertEqual(result["id"], "new-group-id")
        self.assertEqual(result["name"], "Location#All Locations#Building1")
        lookup_call, create_call = self.ise.ers_request.call_args_list
        self.assertEqual(lookup_call.args[0], "networkdevicegroup/name/Location%23All%20Locations")

        self.assertEqual(create_call.args[0], "networkdevicegroup")
        self.assertEqual(create_call.kwargs["method"], "POST")
        payload = create_call.kwargs["data"]["NetworkDeviceGroup"]
        self.assertEqual(payload["name"], "Location#All Locations#Building1")
        self.assertEqual(payload["othername"], "Location")
        self.assertEqual(payload["description"], "HQ building")

    async def test_create_location_omits_description_when_blank(self) -> None:
        self.ise.ers_request.side_effect = [
            {"NetworkDeviceGroup": {"name": "Location#All Locations", "othername": "Location"}},
            {"id": "new-group-id"},
        ]

        await self.service.create_location(
            name="Building1", description=None, parent_group="All Locations"
        )

        _, create_call = self.ise.ers_request.call_args_list
        payload = create_call.kwargs["data"]["NetworkDeviceGroup"]
        self.assertNotIn("description", payload)

    async def test_create_location_supports_nested_parent(self) -> None:
        self.ise.ers_request.side_effect = [
            {
                "NetworkDeviceGroup": {
                    "name": "Location#All Locations#Building1",
                    "othername": "Location",
                }
            },
            {"id": "floor-id"},
        ]

        await self.service.create_location(
            name="Floor1", description=None, parent_group="All Locations#Building1"
        )

        lookup_call, create_call = self.ise.ers_request.call_args_list
        self.assertEqual(
            lookup_call.args[0],
            "networkdevicegroup/name/Location%23All%20Locations%23Building1",
        )
        payload = create_call.kwargs["data"]["NetworkDeviceGroup"]
        self.assertEqual(payload["name"], "Location#All Locations#Building1#Floor1")

    async def test_create_root_group_builds_self_referential_name(self) -> None:
        self.ise.ers_request.return_value = {"id": "root-id"}

        result = await self.service.create_root_group(name="new-root", description="a new root")

        self.assertEqual(result["id"], "root-id")
        self.assertEqual(result["name"], "new-root#new-root")
        self.assertEqual(result["othername"], "new-root")
        self.ise.ers_request.assert_called_once_with(
            "networkdevicegroup",
            _credentials(),
            method="POST",
            data={
                "NetworkDeviceGroup": {
                    "name": "new-root#new-root",
                    "othername": "new-root",
                    "description": "a new root",
                }
            },
        )

    async def test_create_child_group_inherits_parent_othername(self) -> None:
        self.ise.ers_request.side_effect = [
            {"NetworkDeviceGroup": {"name": "new-root#new-root", "othername": "new-root"}},
            {"id": "child-id"},
        ]

        result = await self.service.create_child_group(
            name="location-001", description=None, parent_group="new-root#new-root"
        )

        self.assertEqual(result["name"], "new-root#new-root#location-001")
        self.assertEqual(result["othername"], "new-root")
        _, create_call = self.ise.ers_request.call_args_list
        payload = create_call.kwargs["data"]["NetworkDeviceGroup"]
        self.assertEqual(payload["othername"], "new-root")
        self.assertNotIn("description", payload)

    async def test_create_child_group_raises_when_parent_missing_uses_given_label(self) -> None:
        self.ise.ers_request.side_effect = ISENotFoundError("not found")
        with self.assertRaises(ISEValidationError) as ctx:
            await self.service.create_child_group(
                name="x", description=None, parent_group="Ghost#Ghost"
            )
        self.assertIn("Ghost#Ghost", str(ctx.exception))

    async def test_get_group_requests_by_id(self) -> None:
        self.ise.ers_request.return_value = {"NetworkDeviceGroup": {"id": "abc"}}
        await self.service.get_group("abc")
        self.ise.ers_request.assert_called_once_with(
            "networkdevicegroup/abc", _credentials(), method="GET"
        )

    async def test_update_group_merges_over_current_state(self) -> None:
        self.ise.ers_request.side_effect = [
            {
                "NetworkDeviceGroup": {
                    "id": "abc",
                    "name": "Location#All Locations#Building1",
                    "othername": "Location",
                    "description": "old desc",
                }
            },
            {"UpdatedFieldsList": {}},
        ]

        await self.service.update_group("abc", description="new desc")

        get_call, put_call = self.ise.ers_request.call_args_list
        self.assertEqual(get_call.args[0], "networkdevicegroup/abc")
        self.assertEqual(get_call.kwargs["method"], "GET")

        self.assertEqual(put_call.args[0], "networkdevicegroup/abc")
        self.assertEqual(put_call.kwargs["method"], "PUT")
        merged = put_call.kwargs["data"]["NetworkDeviceGroup"]
        self.assertEqual(merged["name"], "Location#All Locations#Building1")
        self.assertEqual(merged["othername"], "Location")
        self.assertEqual(merged["description"], "new desc")

    async def test_delete_group(self) -> None:
        self.ise.ers_request.return_value = {"status": "success"}
        await self.service.delete_group("abc")
        self.ise.ers_request.assert_called_once_with(
            "networkdevicegroup/abc", _credentials(), method="DELETE"
        )


if __name__ == "__main__":
    unittest.main()
