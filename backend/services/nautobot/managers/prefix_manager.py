"""
Prefix lifecycle manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..common.exceptions import NautobotAPIError
from ..common.utils import normalize_tags
from ..common.validators import is_valid_uuid

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)


class PrefixManager:
    """Manager for IP prefix lifecycle operations."""

    def __init__(
        self,
        nautobot_service: NautobotService,
        network_resolver: NetworkResolver,
        metadata_resolver: MetadataResolver,
    ):
        """
        Initialize the prefix manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            network_resolver: NetworkResolver instance for resolution
            metadata_resolver: MetadataResolver instance for status resolution
        """
        self.nautobot = nautobot_service
        self.network_resolver = network_resolver
        self.metadata_resolver = metadata_resolver

    async def ensure_prefix_exists(
        self,
        prefix: str,
        namespace: str = "Global",
        status: str = "active",
        prefix_type: str = "network",
        location: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Ensure IP prefix exists in Nautobot.

        If prefix already exists in the namespace, returns its UUID.
        If not, creates it and returns the new UUID.

        Args:
            prefix: IP prefix in CIDR format (e.g., "192.168.1.0/24")
            namespace: Namespace name or UUID (default: "Global")
            status: Status name for the prefix (default: "active")
            prefix_type: Type of prefix - "network" or "container" (default: "network")
            location: Location name or UUID (optional)
            description: Description for the prefix (optional)
            **kwargs: Additional fields for prefix creation (role, parent, tenant, vlan, rir, tags, custom_fields)

        Returns:
            Prefix UUID

        Raises:
            Exception: If creation fails and prefix doesn't exist
        """
        logger.info("Ensuring prefix exists: %s in namespace %s", prefix, namespace)

        # Resolve namespace to UUID (or use directly if already UUID)
        if is_valid_uuid(namespace):
            logger.debug("Namespace is already a UUID: %s", namespace)
            namespace_id = namespace
        else:
            namespace_id = await self.network_resolver.resolve_namespace_id(namespace)

        # Check if prefix already exists in this namespace
        prefix_search_endpoint = (
            f"ipam/prefixes/?prefix={prefix}&namespace={namespace_id}&format=json"
        )
        prefix_result = await self.nautobot.rest_request(
            endpoint=prefix_search_endpoint, method="GET"
        )

        if prefix_result and prefix_result.get("count", 0) > 0:
            existing_prefix = prefix_result["results"][0]
            logger.info("Prefix already exists: %s", existing_prefix["id"])
            return existing_prefix["id"]

        # Prefix doesn't exist, create it
        logger.info("Creating new prefix: %s", prefix)

        # Resolve status to UUID
        status_id = await self.metadata_resolver.resolve_status_id(
            status, content_type="ipam.prefix"
        )

        # Build payload - Nautobot REST API expects UUID strings, not nested objects
        prefix_data = {
            "prefix": prefix,
            "namespace": namespace_id,
            "status": status_id,
            "type": prefix_type,
        }

        # Add optional description
        if description:
            prefix_data["description"] = description

        # Resolve location if provided
        if location:
            if is_valid_uuid(location):
                prefix_data["location"] = location
            else:
                location_id = await self.metadata_resolver.resolve_location_id(location)
                if location_id:
                    prefix_data["location"] = location_id
                else:
                    logger.warning(
                        "Location '%s' not found, prefix will be created without location",
                        location,
                    )

        # Add optional fields from kwargs
        optional_uuid_fields = ["role", "parent", "tenant", "vlan", "rir"]
        for field in optional_uuid_fields:
            if field in kwargs and kwargs[field]:
                value = kwargs[field]
                if is_valid_uuid(value):
                    prefix_data[field] = value
                else:
                    logger.warning("Field '%s' should be a UUID, got: %s", field, value)

        # Add tags if provided
        if "tags" in kwargs and kwargs["tags"]:
            prefix_data["tags"] = normalize_tags(kwargs["tags"])

        # Add custom_fields if provided
        if "custom_fields" in kwargs and kwargs["custom_fields"]:
            prefix_data["custom_fields"] = kwargs["custom_fields"]

        # Create the prefix
        result = await self.nautobot.rest_request(
            endpoint="ipam/prefixes/", method="POST", data=prefix_data
        )

        if not result or "id" not in result:
            raise NautobotAPIError(f"Failed to create prefix {prefix}: No ID returned")

        prefix_id = result["id"]
        logger.info("Created new prefix: %s with ID: %s", prefix, prefix_id)
        return prefix_id
