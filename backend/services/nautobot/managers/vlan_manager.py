"""
VLAN lifecycle manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.metadata_resolver import MetadataResolver

logger = logging.getLogger(__name__)

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
        raise NautobotAPIError(f"GraphQL errors while resolving VLAN {vid}: {result['errors']}")
    return result.get("data", {}).get("vlans", [])


class VLANManager:
    """Manager for VLAN lookup/creation."""

    def __init__(self, nautobot_service: NautobotService, metadata_resolver: MetadataResolver):
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
        status_id = await self.metadata_resolver.resolve_status_id(
            status, content_type="ipam.vlan"
        )
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
