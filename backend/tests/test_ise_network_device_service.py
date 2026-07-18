"""Tests for ISENetworkDeviceService (mocked ISEService, no real network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from services.ise.common.exceptions import ISEValidationError
from services.ise.credentials import ISECredentials
from services.ise.network_device_service import ISENetworkDeviceService


def _credentials() -> ISECredentials:
    return ISECredentials(base_url="https://10.10.20.77", username="admin", password="secret")


class ISENetworkDeviceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ise = AsyncMock()
        self.service = ISENetworkDeviceService(self.ise, _credentials())

    async def test_list_devices_passes_pagination_and_filter(self) -> None:
        self.ise.ers_request.return_value = {"SearchResult": {"total": 0, "resources": []}}
        await self.service.list_devices(page=2, size=50, filter_="name.CONTAINS.router")
        self.ise.ers_request.assert_called_once_with(
            "networkdevice",
            _credentials(),
            method="GET",
            params={"page": 2, "size": 50, "filter": "name.CONTAINS.router"},
        )

    async def test_list_devices_without_filter_omits_param(self) -> None:
        self.ise.ers_request.return_value = {"SearchResult": {"total": 0, "resources": []}}
        await self.service.list_devices()
        _, kwargs = self.ise.ers_request.call_args
        self.assertNotIn("filter", kwargs["params"])

    async def test_create_device_wraps_payload(self) -> None:
        self.ise.ers_request.return_value = {"id": "new-id"}
        await self.service.create_device({"name": "router1"})
        self.ise.ers_request.assert_called_once_with(
            "networkdevice",
            _credentials(),
            method="POST",
            data={"NetworkDevice": {"name": "router1"}},
        )

    async def test_create_device_without_name_raises(self) -> None:
        with self.assertRaises(ISEValidationError):
            await self.service.create_device({"description": "no name"})
        self.ise.ers_request.assert_not_called()

    async def test_update_device_merges_over_current_state(self) -> None:
        self.ise.ers_request.side_effect = [
            {
                "NetworkDevice": {
                    "id": "abc",
                    "name": "router1",
                    "description": "orig",
                    "authenticationSettings": {"radiusSharedSecret": "keep-me"},
                    "NetworkDeviceIPList": [{"ipaddress": "192.0.2.10", "mask": 32}],
                    "link": {"rel": "self", "href": "https://x"},
                }
            },
            {"UpdatedFieldsList": {}},
        ]

        await self.service.update_device("abc", {"description": "new desc"})

        get_call, put_call = self.ise.ers_request.call_args_list
        self.assertEqual(get_call.args[0], "networkdevice/abc")
        self.assertEqual(get_call.kwargs["method"], "GET")

        self.assertEqual(put_call.args[0], "networkdevice/abc")
        self.assertEqual(put_call.kwargs["method"], "PUT")
        merged = put_call.kwargs["data"]["NetworkDevice"]
        self.assertEqual(merged["description"], "new desc")
        self.assertEqual(merged["authenticationSettings"], {"radiusSharedSecret": "keep-me"})
        self.assertEqual(merged["NetworkDeviceIPList"], [{"ipaddress": "192.0.2.10", "mask": 32}])
        self.assertNotIn("link", merged)

    async def test_delete_device(self) -> None:
        self.ise.ers_request.return_value = {"status": "success"}
        await self.service.delete_device("abc")
        self.ise.ers_request.assert_called_once_with(
            "networkdevice/abc", _credentials(), method="DELETE"
        )

    async def test_test_connection_requests_single_page(self) -> None:
        self.ise.ers_request.return_value = {"SearchResult": {"total": 0, "resources": []}}
        await self.service.test_connection()
        self.ise.ers_request.assert_called_once_with(
            "networkdevice", _credentials(), method="GET", params={"size": 1}
        )


if __name__ == "__main__":
    unittest.main()
