"""
VLAN lifecycle manager.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from services.nautobot.common.rest import rest_paginate, rest_query
from services.nautobot.common.validators import is_valid_uuid

from ..common.exceptions import (
    NautobotAmbiguousMatchError,
    NautobotAPIError,
    NautobotNotFoundError,
)
from ..common.utils import graphql_errors_summary

if TYPE_CHECKING:
    from services.nautobot.api_protocol import NautobotApi

    from ..resolvers.metadata_resolver import MetadataResolver

logger = logging.getLogger(__name__)

# Fields that hold a related object's id; a UUID is compared and sent in lower case.
_ID_FIELDS = frozenset({"status", "role"})


class VlanPartialUpdateError(NautobotAPIError):
    """A VLAN write failed after earlier writes had already been stored.

    ``applied`` names what is stored (``"fields"``, ``"locations"``); the original error is the
    ``__cause__``. Nautobot has no transaction across the calls, so a second run completes it.
    """

    def __init__(self, applied: Sequence[str]) -> None:
        super().__init__("VLAN update stopped part-way: " + ", ".join(applied) + " already written")
        self.applied = tuple(applied)


LocationsMode = Literal["replace", "add", "remove"]
LOCATIONS_MODES: tuple[str, ...] = ("replace", "add", "remove")

_VLANS_BY_VID_QUERY = """
query GetVlans($vid: [Int], $location: [String]) {
  vlans(vid: $vid, location: $location) {
    id
    name
  }
}
"""


async def _query_vlans(nautobot, vid: int, location_id: str | None) -> list[dict[str, Any]]:
    variables: dict[str, Any] = {"vid": [vid]}
    if location_id:
        variables["location"] = [location_id]
    result = await nautobot.graphql_query(_VLANS_BY_VID_QUERY, variables)
    if "errors" in result:
        raise NautobotAPIError(
            graphql_errors_summary(result["errors"], f"while resolving VLAN {vid}")
        )
    return result.get("data", {}).get("vlans", [])


def _reference_id(value: object) -> object:
    """A related object arrives as a UUID or as a nested object; compare by its id."""
    return value.get("id") if isinstance(value, dict) else value


def _normalize_id(key: str, value: str) -> str:
    return value.lower() if key in _ID_FIELDS and is_valid_uuid(value.lower()) else value


def merge_locations(
    current: Sequence[str], requested: Sequence[str], mode: LocationsMode
) -> list[str]:
    """The location ids a VLAN has after applying ``requested`` in ``mode``."""
    if mode == "replace":
        return list(dict.fromkeys(requested))
    if mode == "add":
        return list(dict.fromkeys([*current, *requested]))
    drop = set(requested)
    return [item for item in current if item not in drop]


class VLANManager:
    """Manager for VLAN lookup/creation."""

    def __init__(self, nautobot_service: NautobotApi, metadata_resolver: MetadataResolver):
        """
        Initialize the VLAN manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            metadata_resolver: MetadataResolver instance for status resolution
        """
        self.nautobot = nautobot_service
        self.metadata_resolver = metadata_resolver

    async def resolve_vlan_id(self, vid: int, location_id: str | None = None) -> str | None:
        """Look up a VLAN by vid, optionally scoped to a location.

        Tries a location-scoped lookup first when ``location_id`` is given;
        falls back to an unscoped vid-only lookup when that finds nothing (or
        no location was given at all). Returns the first match's UUID, or
        ``None`` if neither lookup finds anything.
        """
        if location_id:
            vlans = await _query_vlans(self.nautobot, vid, location_id)
            if vlans:
                return vlans[0]["id"]

        vlans = await _query_vlans(self.nautobot, vid, None)
        if vlans:
            return vlans[0]["id"]
        return None

    async def ensure_vlan_exists(
        self,
        vid: int,
        location_id: str | None = None,
        status: str = "active",
        name: str | None = None,
    ) -> str:
        """Ensure a VLAN exists for ``vid``; return the existing or newly created UUID."""
        existing_id = await self.resolve_vlan_id(vid, location_id)
        if existing_id:
            logger.info("VLAN already exists: vid=%s id=%s", vid, existing_id)
            return existing_id

        logger.info("Creating new VLAN vid=%s location=%s", vid, location_id)
        status_id = await self.metadata_resolver.resolve_status_id(status, content_type="ipam.vlan")
        vlan_data: dict[str, Any] = {
            "vid": vid,
            "name": name or f"vlan-{vid}",
            "status": status_id,
        }
        if location_id:
            vlan_data["locations"] = [location_id]

        result = await self.nautobot.rest_request(
            endpoint="ipam/vlans/", method="POST", data=vlan_data
        )
        if not result or "id" not in result:
            raise NautobotAPIError(f"Failed to create VLAN {vid}: No ID returned")

        vlan_id = result["id"]
        logger.info("Created new VLAN vid=%s with ID: %s", vid, vlan_id)
        return vlan_id

    async def find_vlans(self, vid: int, vlan_group_id: str | None = None) -> list[str]:
        """Ids of the VLANs with this VID, narrowed to a VLAN group when one is given.

        Raises:
            NautobotAPIError: If Nautobot refuses the lookup.
        """
        params: dict[str, Any] = {"vid": vid, "limit": 1000, "format": "json"}
        if vlan_group_id:
            params["vlan_group"] = vlan_group_id
        rows = await rest_paginate(self.nautobot, f"ipam/vlans/?{rest_query(**params)}")
        return [str(row["id"]) for row in rows if row.get("id")]

    async def _resolve_by_name(self, endpoint: str, label: str, name: str) -> str:
        """One object id from a name (compared case-insensitively) or a UUID.

        A UUID is checked to exist, so an unknown one is "not found" here and not a confusing
        empty result later. A name that matches only in another case is used when it is the only
        match; an exact-case match wins over such matches.

        Raises:
            ValueError: If no object has this name or id.
            NautobotAmbiguousMatchError: If several objects have it.
        """
        if is_valid_uuid(name.lower()):
            try:
                row = await self.nautobot.rest_request(
                    endpoint=f"{endpoint}{name.lower()}/?format=json", method="GET"
                )
            except NautobotNotFoundError as exc:
                raise ValueError(f"{label} not found") from exc
            return str(row.get("id") or name.lower())
        rows = await rest_paginate(
            self.nautobot, f"{endpoint}?{rest_query(name__ic=name, limit=1000, format='json')}"
        )
        matches = [row for row in rows if str(row.get("name", "")).lower() == name.lower()]
        exact = [row for row in matches if str(row.get("name")) == name]
        matches = exact or matches
        if not matches:
            raise ValueError(f"{label} not found")
        if len(matches) > 1:
            raise NautobotAmbiguousMatchError(f"More than one {label} matches the name")
        return str(matches[0]["id"])

    async def resolve_vlan_group_id(self, name: str) -> str:
        """VLAN group id from a name or UUID."""
        return await self._resolve_by_name("ipam/vlan-groups/", "VLAN group", name)

    async def resolve_location_id_strict(self, name: str) -> str:
        """Location id from a name or UUID; an unknown or ambiguous name raises."""
        return await self._resolve_by_name("dcim/locations/", "Location", name)

    async def update_vlan(
        self,
        vlan_id: str,
        fields: Mapping[str, str],
        *,
        locations: Sequence[str] = (),
        locations_mode: LocationsMode = "replace",
    ) -> bool:
        """
        Update an existing VLAN; only the values that differ are sent.

        Args:
            vlan_id: VLAN UUID
            fields: Nautobot REST fields to set (``status`` and ``role`` as ids, ``name`` and
                ``description`` as text)
            locations: Location ids to apply in ``locations_mode``; empty leaves them alone
            locations_mode: ``replace`` sets the exact list, ``add`` keeps the current ones and
                adds, ``remove`` drops the given ones

        Returns:
            True when a PATCH was sent, False when the VLAN already had every value.

        Raises:
            ValueError: If ``vlan_id`` is not a UUID or the mode is unknown.
            NautobotNotFoundError: If the VLAN does not exist.
            NautobotAPIError: If Nautobot refuses the change.
        """
        if not is_valid_uuid(vlan_id.lower()):
            raise ValueError("vlan_id is not a Nautobot UUID")
        if locations_mode not in LOCATIONS_MODES:
            raise ValueError("locations_mode is not valid")
        endpoint = f"ipam/vlans/{vlan_id}/?format=json"
        current = await self.nautobot.rest_request(endpoint=endpoint, method="GET")
        wanted = {key: _normalize_id(key, value) for key, value in fields.items()}
        changes: dict[str, Any] = {
            key: value for key, value in wanted.items() if _reference_id(current.get(key)) != value
        }
        applied: list[str] = []
        try:
            if changes:
                logger.info("Updating VLAN %s fields=%s", vlan_id, sorted(changes))
                await self.nautobot.rest_request(
                    endpoint=f"ipam/vlans/{vlan_id}/", method="PATCH", data=changes
                )
                applied.append("fields")
            relocated = await self._apply_locations(vlan_id, locations, locations_mode)
        except VlanPartialUpdateError as exc:
            raise VlanPartialUpdateError([*applied, *exc.applied]) from exc.__cause__
        except Exception as exc:
            # Something is stored already: say so instead of reporting a plain failure.
            if applied:
                raise VlanPartialUpdateError(applied) from exc
            raise
        if not changes and not relocated:
            logger.info("VLAN %s already has the requested values", vlan_id)
        return bool(changes) or relocated

    async def _apply_locations(
        self, vlan_id: str, requested: Sequence[str], mode: LocationsMode
    ) -> bool:
        """Create / delete location assignments so the VLAN's locations match; True if any changed.

        Nautobot exposes ``locations`` read-only on a VLAN (a PATCH of it is silently ignored);
        the set is the ``ipam/vlan-location-assignments/`` rows (one per VLAN and location).
        """
        if not requested:
            return False
        query = rest_query(vlan=vlan_id, limit=1000, format="json")
        rows = await rest_paginate(self.nautobot, f"ipam/vlan-location-assignments/?{query}")
        assigned = {str(_reference_id(row.get("location"))): str(row["id"]) for row in rows}
        wanted = merge_locations(list(assigned), requested, mode)
        to_add = [location for location in wanted if location not in assigned]
        to_remove = [row_id for location, row_id in assigned.items() if location not in wanted]
        written = 0
        try:
            for location in to_add:
                await self.nautobot.rest_request(
                    endpoint="ipam/vlan-location-assignments/",
                    method="POST",
                    data={"vlan": vlan_id, "location": location},
                )
                written += 1
            for row_id in to_remove:
                await self.nautobot.rest_request(
                    endpoint=f"ipam/vlan-location-assignments/{row_id}/", method="DELETE"
                )
                written += 1
        except Exception as exc:
            if written:
                raise VlanPartialUpdateError(["locations"]) from exc
            raise
        if to_add or to_remove:
            logger.info(
                "VLAN %s locations added=%d removed=%d", vlan_id, len(to_add), len(to_remove)
            )
        return bool(to_add or to_remove)
