"""Cisco ISE ERS NetworkDevice CRUD operations."""

from __future__ import annotations

from typing import Any

from services.ise.client import ISEService
from services.ise.common.exceptions import ISEValidationError
from services.ise.credentials import ISECredentials

_ENDPOINT = "networkdevice"


class ISENetworkDeviceService:
    def __init__(self, ise: ISEService, credentials: ISECredentials) -> None:
        self._ise = ise
        self._credentials = credentials

    async def list_devices(
        self,
        *,
        page: int = 1,
        size: int = 20,
        filter_: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "size": size}
        if filter_:
            params["filter"] = filter_
        return await self._ise.ers_request(
            _ENDPOINT, self._credentials, method="GET", params=params
        )

    async def list_devices_by_group(
        self,
        group_name: str,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """List devices whose ``NetworkDeviceGroupList`` contains ``group_name``.

        ISE's ERS ``location`` filter field is documented (and named) as a
        Location-category filter, but confirmed live it actually matches
        against ANY entry in a device's ``NetworkDeviceGroupList`` regardless
        of category — filtering by a custom group (e.g.
        ``myGroup#myGroup#my-test-001``) or a non-Location built-in group
        (``Device Type#All Device Types``, ``IPSEC#Is IPSEC Device#No``)
        returns the same devices as filtering by an actual
        ``Location#...`` group. ``group_name`` must be the full
        hierarchical NDG name.
        """
        return await self.list_devices(page=page, size=size, filter_=f"location.EQ.{group_name}")

    async def get_device(self, device_id: str) -> dict[str, Any]:
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{device_id}", self._credentials, method="GET"
        )

    async def get_device_by_name(self, name: str) -> dict[str, Any]:
        return await self._ise.ers_request(
            f"{_ENDPOINT}/name/{name}", self._credentials, method="GET"
        )

    async def create_device(self, device: dict[str, Any]) -> dict[str, Any]:
        if not device.get("name"):
            raise ISEValidationError("Device name is required")
        return await self._ise.ers_request(
            _ENDPOINT,
            self._credentials,
            method="POST",
            data={"NetworkDevice": device},
        )

    async def update_device(self, device_id: str, device: dict[str, Any]) -> dict[str, Any]:
        """Merge-and-replace update.

        ISE's ERS PUT replaces the whole NetworkDevice representation for any
        top-level field it receives — fields omitted from the payload (e.g.
        authenticationSettings, description) are cleared, not left untouched.
        Fetch the current device and shallow-merge the requested changes over
        it so callers get expected "partial update" semantics.
        """
        current = await self.get_device(device_id)
        current_device = current.get("NetworkDevice", {})
        merged = {**current_device, **device}
        merged.pop("link", None)
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{device_id}",
            self._credentials,
            method="PUT",
            data={"NetworkDevice": merged},
        )

    async def delete_device(self, device_id: str) -> dict[str, Any]:
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{device_id}", self._credentials, method="DELETE"
        )

    async def test_connection(self) -> dict[str, Any]:
        return await self._ise.ers_request(
            _ENDPOINT, self._credentials, method="GET", params={"size": 1}
        )
