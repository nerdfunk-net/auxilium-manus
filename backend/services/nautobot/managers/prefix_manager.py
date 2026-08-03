"""
Prefix lifecycle manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..common.exceptions import NautobotAPIError
from ..common.utils import normalize_tags
from ..common.validators import is_valid_uuid

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)


async def _resolve_namespace_ref(network_resolver, namespace: str) -> str:
    if is_valid_uuid(namespace):
        logger.debug("Namespace is already a UUID: %s", namespace)
        return namespace
    return await network_resolver.resolve_namespace_id(namespace)


async def _find_prefix_id(nautobot, prefix: str, namespace_id: str) -> str | None:
    prefix_search_endpoint = (
        f"ipam/prefixes/?prefix={prefix}&namespace={namespace_id}&format=json"
    )
    prefix_result = await nautobot.rest_request(endpoint=prefix_search_endpoint, method="GET")
    if prefix_result and prefix_result.get("count", 0) > 0:
        return prefix_result["results"][0]["id"]
    return None


async def _attach_optional_location(
    metadata_resolver,
    prefix_data: dict,
    location: str,
) -> None:
    if is_valid_uuid(location):
        prefix_data["location"] = location
        return
    location_id = await metadata_resolver.resolve_location_id(location)
    if location_id:
        prefix_data["location"] = location_id
    else:
        logger.warning(
            "Location '%s' not found, prefix will be created without location",
            location,
        )


async def _build_prefix_create_payload(
    *,
    metadata_resolver,
    prefix: str,
    namespace_id: str,
    status_id: str,
    prefix_type: str,
    location: str | None,
    description: str | None,
    kwargs: dict,
) -> dict:
    prefix_data = {
        "prefix": prefix,
        "namespace": namespace_id,
        "status": status_id,
        "type": prefix_type,
    }

    if description:
        prefix_data["description"] = description

    if location:
        await _attach_optional_location(metadata_resolver, prefix_data, location)

    optional_uuid_fields = ["role", "parent", "tenant", "vlan", "rir"]
    for field in optional_uuid_fields:
        if field in kwargs and kwargs[field]:
            value = kwargs[field]
            if is_valid_uuid(value):
                prefix_data[field] = value
            else:
                logger.warning("Field '%s' should be a UUID, got: %s", field, value)

    if "tags" in kwargs and kwargs["tags"]:
        prefix_data["tags"] = normalize_tags(kwargs["tags"])

    if "custom_fields" in kwargs and kwargs["custom_fields"]:
        prefix_data["custom_fields"] = kwargs["custom_fields"]

    return prefix_data


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
        location: str | None = None,
        description: str | None = None,
        **kwargs,
    ) -> str:
        """Ensure IP prefix exists; return existing or newly created UUID."""
        logger.info("Ensuring prefix exists: %s in namespace %s", prefix, namespace)

        namespace_id = await _resolve_namespace_ref(self.network_resolver, namespace)
        existing_id = await _find_prefix_id(self.nautobot, prefix, namespace_id)
        if existing_id:
            logger.info("Prefix already exists: %s", existing_id)
            return existing_id

        logger.info("Creating new prefix: %s", prefix)
        status_id = await self.metadata_resolver.resolve_status_id(
            status, content_type="ipam.prefix"
        )
        prefix_data = await _build_prefix_create_payload(
            metadata_resolver=self.metadata_resolver,
            prefix=prefix,
            namespace_id=namespace_id,
            status_id=status_id,
            prefix_type=prefix_type,
            location=location,
            description=description,
            kwargs=kwargs,
        )

        result = await self.nautobot.rest_request(
            endpoint="ipam/prefixes/", method="POST", data=prefix_data
        )
        if not result or "id" not in result:
            raise NautobotAPIError(f"Failed to create prefix {prefix}: No ID returned")

        prefix_id = result["id"]
        logger.info("Created new prefix: %s with ID: %s", prefix, prefix_id)
        return prefix_id
