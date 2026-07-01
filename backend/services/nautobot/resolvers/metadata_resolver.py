"""
Metadata resolver for Status, Role, Platform, Location resolution.
"""

import logging
from typing import Optional

from ..common.validators import is_valid_uuid
from .base_resolver import BaseResolver

logger = logging.getLogger(__name__)


class MetadataResolver(BaseResolver):
    """Resolver for metadata entities (Status, Role, Platform, Location, etc.)."""

    async def resolve_status_id(
        self, status_name: str, content_type: str = "dcim.device"
    ) -> str:
        """
        Resolve a status name to its UUID using REST API.

        If status_name is already a valid UUID, returns it directly.

        Args:
            status_name: Name of the status (e.g., "active", "planned") or UUID
            content_type: Content type for the status
                         (e.g., "dcim.device", "dcim.interface", "ipam.ipaddress")

        Returns:
            Status UUID

        Raises:
            ValueError: If status not found
        """
        # If already a UUID, return directly
        if is_valid_uuid(status_name):
            logger.debug("Status is already a UUID: %s", status_name)
            return status_name

        logger.info(
            "Resolving status '%s' for content type '%s'", status_name, content_type
        )

        # Query for statuses filtered by content type
        endpoint = f"extras/statuses/?content_types={content_type}&format=json"
        result = await self.nautobot.rest_request(endpoint=endpoint, method="GET")

        if result and result.get("count", 0) > 0:
            for status in result.get("results", []):
                if status.get("name", "").lower() == status_name.lower():
                    logger.info(
                        "Resolved status '%s' to UUID %s", status_name, status["id"]
                    )
                    return status["id"]

        raise ValueError(
            f"Status '{status_name}' not found for content type '{content_type}'"
        )

    async def resolve_role_id(self, role_name: str) -> Optional[str]:
        """
        Resolve role name to UUID using GraphQL.

        Args:
            role_name: Name of the role

        Returns:
            Role UUID if found, None otherwise
        """
        try:
            logger.info("Resolving role '%s'", role_name)

            query = """
            query GetRole($name: [String]) {
              roles(name: $name) {
                id
                name
              }
            }
            """
            variables = {"name": [role_name]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving role: %s", result["errors"])
                return None

            roles = result.get("data", {}).get("roles", [])
            if roles and len(roles) > 0:
                role_id = roles[0]["id"]
                logger.info("Resolved role '%s' to UUID %s", role_name, role_id)
                return role_id

            logger.warning("Role not found: %s", role_name)
            return None

        except Exception as e:
            logger.error("Error resolving role: %s", e, exc_info=True)
            return None

    async def resolve_platform_id(self, platform_name: str) -> Optional[str]:
        """
        Resolve platform name to UUID using GraphQL.

        Args:
            platform_name: Name of the platform

        Returns:
            Platform UUID if found, None otherwise
        """
        try:
            logger.info("Resolving platform '%s'", platform_name)

            query = """
            query GetPlatform($name: [String]) {
              platforms(name: $name) {
                id
                name
              }
            }
            """
            variables = {"name": [platform_name]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving platform: %s", result["errors"])
                return None

            platforms = result.get("data", {}).get("platforms", [])
            if platforms and len(platforms) > 0:
                platform_id = platforms[0]["id"]
                logger.info(
                    "Resolved platform '%s' to UUID %s", platform_name, platform_id
                )
                return platform_id

            logger.warning("Platform not found: %s", platform_name)
            return None

        except Exception as e:
            logger.error("Error resolving platform: %s", e, exc_info=True)
            return None

    async def get_platform_name(self, platform_id: str) -> Optional[str]:
        """
        Get platform display name from UUID using REST API.

        Args:
            platform_id: Platform UUID

        Returns:
            Platform name if found, None otherwise
        """
        try:
            logger.debug("Fetching platform name for UUID: %s", platform_id)

            result = await self.nautobot.rest_request(
                endpoint=f"dcim/platforms/{platform_id}/", method="GET"
            )

            if result and "name" in result:
                platform_name = result["name"]
                logger.debug("Platform UUID %s -> name: %s", platform_id, platform_name)
                return platform_name

            logger.warning("Platform not found for UUID: %s", platform_id)
            return None

        except Exception as e:
            logger.error("Error fetching platform name: %s", e, exc_info=True)
            return None

    async def resolve_location_id(self, location_name: str) -> Optional[str]:
        """
        Resolve location name to UUID using GraphQL.

        Args:
            location_name: Name of the location

        Returns:
            Location UUID if found, None otherwise
        """
        try:
            logger.info("Resolving location '%s'", location_name)

            query = """
            query GetLocation($name: [String]) {
              locations(name: $name) {
                id
                name
              }
            }
            """
            variables = {"name": [location_name]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving location: %s", result["errors"])
                return None

            locations = result.get("data", {}).get("locations", [])
            if locations and len(locations) > 0:
                location_id = locations[0]["id"]
                logger.info(
                    "Resolved location '%s' to UUID %s", location_name, location_id
                )
                return location_id

            logger.warning("Location not found: %s", location_name)
            return None

        except Exception as e:
            logger.error("Error resolving location: %s", e, exc_info=True)
            return None

    async def resolve_secrets_group_id(self, group_name: str) -> Optional[str]:
        """
        Resolve secrets group name to UUID using GraphQL.

        Args:
            group_name: Name of the secrets group

        Returns:
            Secrets group UUID if found, None otherwise
        """
        try:
            logger.info("Resolving secrets group '%s'", group_name)

            query = """
            query GetSecretsGroup($name: [String]) {
              secrets_groups(name: $name) {
                id
                name
              }
            }
            """
            variables = {"name": [group_name]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error(
                    "GraphQL error resolving secrets group: %s", result["errors"]
                )
                return None

            groups = result.get("data", {}).get("secrets_groups", [])
            if groups and len(groups) > 0:
                group_id = groups[0]["id"]
                logger.info(
                    "Resolved secrets group '%s' to UUID %s", group_name, group_id
                )
                return group_id

            logger.warning("Secrets group not found: %s", group_name)
            return None

        except Exception as e:
            logger.error("Error resolving secrets group: %s", e, exc_info=True)
            return None

    async def resolve_rack_id(
        self, rack_name: str, location: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve rack name to UUID using REST API.

        If location is provided, the query is filtered by that location name so that
        racks with the same name in different locations can be disambiguated.
        When the filtered query returns more than one result an exception is raised
        because the correct rack cannot be determined.

        Args:
            rack_name: Name of the rack (e.g., "A_1", "Rack-01") or UUID
            location: Optional location name used to narrow the search

        Returns:
            Rack UUID if found, None otherwise

        Raises:
            ValueError: If more than one rack matches rack_name in the given location
        """
        if is_valid_uuid(rack_name):
            logger.debug("Rack is already a UUID: %s", rack_name)
            return rack_name

        try:
            logger.info(
                "Resolving rack '%s' (location filter: %s)", rack_name, location
            )

            endpoint = f"dcim/racks/?name={rack_name}&format=json"
            if location:
                endpoint += f"&location={location}"

            result = await self.nautobot.rest_request(endpoint=endpoint, method="GET")

            count = result.get("count", 0) if result else 0

            if count == 0:
                logger.warning("Rack not found: %s", rack_name)
                return None

            if count > 1:
                raise ValueError(
                    f"Rack '{rack_name}' is ambiguous: {count} racks with this name "
                    f"exist in location '{location}'. "
                    "Cannot determine the correct rack — device will not be updated."
                )

            rack_id = result["results"][0]["id"]
            logger.info("Resolved rack '%s' to UUID %s", rack_name, rack_id)
            return rack_id

        except ValueError:
            raise
        except Exception as e:
            logger.error("Error resolving rack: %s", e, exc_info=True)
            return None
