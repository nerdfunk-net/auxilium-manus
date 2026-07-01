"""
Network resolver for IP addresses, Interfaces, Namespaces, Prefixes resolution.
"""

import logging
from typing import Optional

from ..common.validators import is_valid_uuid
from .base_resolver import BaseResolver

logger = logging.getLogger(__name__)


class NetworkResolver(BaseResolver):
    """Resolver for network resources (IP addresses, Interfaces, Namespaces, Prefixes)."""

    async def resolve_namespace_id(self, namespace_name: str) -> str:
        """
        Resolve a namespace name to its UUID using GraphQL.

        If namespace_name is already a valid UUID, returns it directly.

        Args:
            namespace_name: Name of the namespace (e.g., "Global") or UUID

        Returns:
            Namespace UUID

        Raises:
            ValueError: If namespace not found
        """
        # If already a UUID, return directly
        if is_valid_uuid(namespace_name):
            logger.debug("Namespace is already a UUID: %s", namespace_name)
            return namespace_name

        logger.info("Resolving namespace '%s'", namespace_name)

        query = """
        query GetNamespace($name: [String]) {
            namespaces(name: $name) {
                id
                name
            }
        }
        """
        variables = {"name": [namespace_name]}
        result = await self.nautobot.graphql_query(query, variables)

        if "errors" in result:
            raise ValueError(
                f"GraphQL errors while resolving namespace: {result['errors']}"
            )

        namespaces = result.get("data", {}).get("namespaces", [])
        if namespaces:
            namespace_id = namespaces[0]["id"]
            logger.info(
                "Resolved namespace '%s' to UUID %s", namespace_name, namespace_id
            )
            return namespace_id

        raise ValueError(f"Namespace '{namespace_name}' not found")

    async def resolve_ip_address(
        self, ip_address: str, namespace_id: str
    ) -> Optional[str]:
        """
        Resolve IP address UUID from address and namespace using GraphQL.

        Args:
            ip_address: IP address string (e.g., "192.168.1.1/24")
            namespace_id: Namespace UUID

        Returns:
            IP address UUID if found, None otherwise
        """
        try:
            logger.debug(
                "Resolving IP address '%s' in namespace %s", ip_address, namespace_id
            )

            query = """
            query GetIPAddress($filter: [String], $namespace: [String]) {
              ip_addresses(address: $filter, namespace: $namespace) {
                id
                address
              }
            }
            """
            variables = {"filter": [ip_address], "namespace": [namespace_id]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving IP address: %s", result["errors"])
                return None

            ip_addresses = result.get("data", {}).get("ip_addresses", [])
            if ip_addresses and len(ip_addresses) > 0:
                ip_id = ip_addresses[0]["id"]
                logger.debug("Resolved IP address '%s' to UUID %s", ip_address, ip_id)
                return ip_id

            logger.debug("IP address not found: %s", ip_address)
            return None

        except Exception as e:
            logger.error("Error resolving IP address: %s", e, exc_info=True)
            return None

    async def resolve_interface_by_name(
        self, device_id: str, interface_name: str
    ) -> Optional[str]:
        """
        Resolve interface UUID from device ID and interface name using GraphQL.

        Args:
            device_id: Device UUID
            interface_name: Name of the interface

        Returns:
            Interface UUID if found, None otherwise
        """
        try:
            logger.debug(
                "Resolving interface '%s' on device %s", interface_name, device_id
            )

            query = """
            query GetInterface($device: [String], $name: [String]) {
              interfaces(device_id: $device, name: $name) {
                id
                name
              }
            }
            """
            variables = {"device": [device_id], "name": [interface_name]}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving interface: %s", result["errors"])
                return None

            interfaces = result.get("data", {}).get("interfaces", [])
            if interfaces and len(interfaces) > 0:
                interface_id = interfaces[0]["id"]
                logger.debug(
                    "Resolved interface '%s' to UUID %s", interface_name, interface_id
                )
                return interface_id

            logger.debug("Interface not found: %s", interface_name)
            return None

        except Exception as e:
            logger.error("Error resolving interface: %s", e, exc_info=True)
            return None

    async def resolve_prefix(self, prefix: str, namespace_id: str) -> Optional[str]:
        """
        Resolve prefix UUID from prefix and namespace.

        Args:
            prefix: IP prefix in CIDR format (e.g., "192.168.1.0/24")
            namespace_id: Namespace UUID

        Returns:
            Prefix UUID if found, None otherwise
        """
        try:
            logger.debug("Resolving prefix '%s' in namespace %s", prefix, namespace_id)

            # Use REST API for prefix lookup
            prefix_search_endpoint = (
                f"ipam/prefixes/?prefix={prefix}&namespace={namespace_id}&format=json"
            )
            prefix_result = await self.nautobot.rest_request(
                endpoint=prefix_search_endpoint, method="GET"
            )

            if prefix_result and prefix_result.get("count", 0) > 0:
                prefix_id = prefix_result["results"][0]["id"]
                logger.debug("Resolved prefix '%s' to UUID %s", prefix, prefix_id)
                return prefix_id

            logger.debug("Prefix not found: %s", prefix)
            return None

        except Exception as e:
            logger.error("Error resolving prefix: %s", e, exc_info=True)
            return None
