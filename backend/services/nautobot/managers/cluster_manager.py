"""
Cluster manager for Nautobot virtualization cluster lifecycle operations.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot import NautobotService

logger = logging.getLogger(__name__)


def slug_from_name(name: str) -> str:
    """Derive a Nautobot-compatible slug from a display name."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "cluster-type"


class ClusterManager:
    """Manager for virtualization cluster create operations."""

    def __init__(self, nautobot_service: NautobotService):
        self.nautobot = nautobot_service

    async def create_cluster_type(
        self,
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a virtualization cluster type in Nautobot.

        Args:
            name: Cluster type name (required)
            slug: Optional slug (derived from name when omitted)
            description: Optional description
            tags: Optional list of tag UUIDs

        Returns:
            Nautobot REST API response for the created cluster type

        Raises:
            NautobotAPIError: If the Nautobot API request fails
        """
        payload: Dict[str, Any] = {
            "name": name,
            "slug": slug or slug_from_name(name),
        }

        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = [{"id": tag_id} for tag_id in tags]

        try:
            result = await self.nautobot.rest_request(
                "virtualization/cluster-types/",
                method="POST",
                data=payload,
            )
            logger.info("Created cluster type '%s' with ID %s", name, result.get("id"))
            return result
        except NautobotAPIError as e:
            logger.error(
                "Failed to create cluster type '%s': %s", name, e, exc_info=True
            )
            raise NautobotAPIError(f"Failed to create cluster type: {str(e)}") from e

    async def create_cluster(
        self,
        name: str,
        description: Optional[str] = None,
        cluster_type_id: Optional[str] = None,
        cluster_group_id: Optional[str] = None,
        location_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a virtualization cluster in Nautobot.

        Args:
            name: Cluster name (required)
            description: Optional description
            cluster_type_id: Optional cluster type UUID
            cluster_group_id: Optional cluster group UUID
            location_id: Optional location UUID
            tags: Optional list of tag UUIDs

        Returns:
            Nautobot REST API response for the created cluster

        Raises:
            NautobotAPIError: If the Nautobot API request fails
        """
        payload: Dict[str, Any] = {"name": name}

        if description:
            payload["description"] = description
        if cluster_type_id:
            payload["cluster_type"] = {"id": cluster_type_id}
        if cluster_group_id:
            payload["cluster_group"] = {"id": cluster_group_id}
        if location_id:
            payload["location"] = {"id": location_id}
        if tags:
            payload["tags"] = [{"id": tag_id} for tag_id in tags]

        try:
            result = await self.nautobot.rest_request(
                "virtualization/clusters/",
                method="POST",
                data=payload,
            )
            logger.info("Created cluster '%s' with ID %s", name, result.get("id"))
            return result
        except NautobotAPIError as e:
            logger.error("Failed to create cluster '%s': %s", name, e, exc_info=True)
            raise NautobotAPIError(f"Failed to create cluster: {str(e)}") from e
