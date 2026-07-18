"""Cisco ISE ERS NetworkDeviceGroup operations.

ISE encodes group hierarchy entirely inside the ``name`` field as a
``#``-delimited path whose first segment is the group type (``othername``)
— e.g. the built-in root ``Location#All Locations``, with children like
``Location#All Locations#Building1``. A brand-new root category needs at
least two segments too; ISE requires the root member's own leaf name to be
non-empty, and the observed sandbox convention (e.g. ``nautobot#nautobot``)
names it identically to the category, so a new root ``foo`` is stored as
``foo#foo``. ``PUT`` replaces the whole representation like ``NetworkDevice``
does — omitted fields (including ``name``/``othername``) get wiped or
rejected — so updates read-merge-write.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from services.ise.client import ISEService
from services.ise.common.exceptions import ISENotFoundError, ISEValidationError
from services.ise.credentials import ISECredentials

_ENDPOINT = "networkdevicegroup"
LOCATION_GROUP_TYPE = "Location"


class ISENetworkDeviceGroupService:
    def __init__(self, ise: ISEService, credentials: ISECredentials) -> None:
        self._ise = ise
        self._credentials = credentials

    async def list_groups(
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

    async def get_group_by_name(self, name: str) -> dict[str, Any] | None:
        try:
            return await self._ise.ers_request(
                f"{_ENDPOINT}/name/{quote(name, safe='')}",
                self._credentials,
                method="GET",
            )
        except ISENotFoundError:
            return None

    async def get_group(self, group_id: str) -> dict[str, Any]:
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{group_id}", self._credentials, method="GET"
        )

    async def create_root_group(
        self, *, name: str, description: str | None
    ) -> dict[str, Any]:
        """Create a brand-new group category (e.g. a new root like ``nautobot``)."""
        full_name = f"{name}#{name}"
        payload: dict[str, Any] = {"name": full_name, "othername": name}
        if description:
            payload["description"] = description

        result = await self._ise.ers_request(
            _ENDPOINT,
            self._credentials,
            method="POST",
            data={"NetworkDeviceGroup": payload},
        )
        return {**result, "name": full_name, "othername": name}

    async def create_child_group(
        self,
        *,
        name: str,
        description: str | None,
        parent_group: str,
        not_found_label: str | None = None,
    ) -> dict[str, Any]:
        """Create a group under any existing parent (its own full ISE name).

        ``not_found_label``, if given, is shown in the not-found error in
        place of ``parent_group`` — lets callers report the short name a
        caller passed in rather than the internally-qualified full path.
        """
        parent = await self.get_group_by_name(parent_group)
        if parent is None:
            raise ISEValidationError(f"Parent group '{not_found_label or parent_group}' not found")
        othername = parent["NetworkDeviceGroup"]["othername"]

        full_name = f"{parent_group}#{name}"
        payload: dict[str, Any] = {"name": full_name, "othername": othername}
        if description:
            payload["description"] = description

        result = await self._ise.ers_request(
            _ENDPOINT,
            self._credentials,
            method="POST",
            data={"NetworkDeviceGroup": payload},
        )
        return {**result, "name": full_name, "othername": othername}

    async def create_location(
        self,
        *,
        name: str,
        description: str | None,
        parent_group: str,
    ) -> dict[str, Any]:
        """Convenience wrapper: create a child of an existing ``Location`` group."""
        return await self.create_child_group(
            name=name,
            description=description,
            parent_group=f"{LOCATION_GROUP_TYPE}#{parent_group}",
            not_found_label=parent_group,
        )

    async def update_group(self, group_id: str, *, description: str) -> dict[str, Any]:
        current = await self.get_group(group_id)
        current_group = current.get("NetworkDeviceGroup", {})
        merged = {
            "name": current_group.get("name"),
            "othername": current_group.get("othername"),
            "description": description,
        }
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{group_id}",
            self._credentials,
            method="PUT",
            data={"NetworkDeviceGroup": merged},
        )

    async def delete_group(self, group_id: str) -> dict[str, Any]:
        return await self._ise.ers_request(
            f"{_ENDPOINT}/{group_id}", self._credentials, method="DELETE"
        )
