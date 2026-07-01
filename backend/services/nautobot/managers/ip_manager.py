"""
IP address lifecycle manager.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)


class IPManager:
    """Manager for IP address lifecycle operations."""

    def __init__(
        self,
        nautobot_service: NautobotService,
        network_resolver: NetworkResolver,
        metadata_resolver: MetadataResolver,
    ):
        """
        Initialize the IP manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            network_resolver: NetworkResolver instance for resolution
            metadata_resolver: MetadataResolver instance for status resolution
        """
        self.nautobot = nautobot_service
        self.network_resolver = network_resolver
        self.metadata_resolver = metadata_resolver

    async def ensure_ip_address_exists(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str = "active",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
        **kwargs,
    ) -> str:
        """
        Ensure IP address exists in Nautobot.

        If IP already exists, returns its UUID.
        If not, creates it and returns the new UUID.
        If creation fails due to missing prefix and add_prefixes_automatically is True,
        creates the prefix and retries IP creation.
        If creation fails due to duplicate IP with different netmask and use_assigned_ip_if_exists is True,
        finds and returns the existing IP UUID.

        Args:
            ip_address: IP address in CIDR format (e.g., "192.168.1.1/24")
            namespace_id: UUID of the namespace
            status_name: Status name for the IP (default: "active")
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails (default: False)
            use_assigned_ip_if_exists: Use existing IP if it exists with different netmask (default: False)
            **kwargs: Additional fields for IP creation

        Returns:
            IP address UUID

        Raises:
            Exception: If creation fails and IP doesn't exist (or auto-features are disabled)
        """
        logger.info("Ensuring IP address exists: %s", ip_address)

        # Check if IP already exists
        ip_search_endpoint = f"ipam/ip-addresses/?address={ip_address}&namespace={namespace_id}&format=json"
        ip_result = await self.nautobot.rest_request(
            endpoint=ip_search_endpoint, method="GET"
        )

        if ip_result and ip_result.get("count", 0) > 0:
            existing_ip = ip_result["results"][0]
            logger.info("IP address already exists: %s", existing_ip["id"])
            return existing_ip["id"]

        # IP doesn't exist, create it
        logger.info("Creating new IP address: %s", ip_address)

        # Resolve status to UUID
        status_id = await self.metadata_resolver.resolve_status_id(
            status_name, content_type="ipam.ipaddress"
        )

        ip_create_data = {
            "address": ip_address,
            "status": status_id,
            "namespace": namespace_id,
            **kwargs,  # Additional fields from caller
        }

        try:
            ip_create_result = await self.nautobot.rest_request(
                endpoint="ipam/ip-addresses/?format=json",
                method="POST",
                data=ip_create_data,
            )

            ip_id = ip_create_result["id"]
            logger.info("Created IP address: %s", ip_id)
            return ip_id

        except NautobotAPIError as e:
            error_message = str(e)

            # Check if error is due to duplicate IP with different netmask
            if (
                "IP address with this Parent and Host already exists" in error_message
                and use_assigned_ip_if_exists
            ):
                logger.warning(
                    "IP creation failed: IP %s already exists with different netmask. Attempting to find existing IP...",
                    ip_address,
                )

                # Extract the host IP without netmask (e.g., "192.168.1.1/24" -> "192.168.1.1")
                try:
                    ip_obj = ipaddress.ip_interface(ip_address)
                    host_ip = str(ip_obj.ip)

                    logger.info(
                        "Searching for existing IP with host address: %s", host_ip
                    )

                    # Search for IP by host address (without netmask) in the namespace
                    # Nautobot's address filter accepts IP without netmask and returns all IPs with that host
                    ip_search_endpoint = f"ipam/ip-addresses/?address={host_ip}&namespace={namespace_id}&format=json"
                    existing_ip_result = await self.nautobot.rest_request(
                        endpoint=ip_search_endpoint, method="GET"
                    )

                    if existing_ip_result and existing_ip_result.get("count", 0) > 0:
                        # Found at least one IP with this host address
                        existing_ip = existing_ip_result["results"][0]
                        logger.info(
                            "Found existing IP: %s with UUID %s",
                            existing_ip["address"],
                            existing_ip["id"],
                        )

                        # If multiple IPs found with same host, log a warning
                        if existing_ip_result.get("count", 0) > 1:
                            logger.warning(
                                "Multiple IPs found with host %s (%s total), using first: %s",
                                host_ip,
                                existing_ip_result["count"],
                                existing_ip["address"],
                            )

                        return existing_ip["id"]
                    else:
                        logger.error("Could not find existing IP for host %s", host_ip)
                        raise NautobotAPIError(
                            f"IP {host_ip} reported as duplicate but not found in namespace"
                        )

                except (ValueError, NautobotAPIError, KeyError) as lookup_error:
                    logger.error(
                        "Failed to find existing IP for %s: %s",
                        ip_address,
                        lookup_error,
                    )
                    raise NautobotAPIError(
                        f"Failed to create IP {ip_address} and could not find existing IP: {lookup_error}"
                    ) from lookup_error

            # Check if error is due to missing prefix
            elif "No suitable parent Prefix" in error_message:
                if add_prefixes_automatically:
                    logger.warning(
                        "IP creation failed due to missing prefix. Attempting to create prefix automatically..."
                    )

                    # Extract the network prefix from the IP address (e.g., "192.168.1.1/24" -> "192.168.1.0/24")
                    try:
                        ip_obj = ipaddress.ip_interface(ip_address)
                        network_prefix = str(ip_obj.network)

                        logger.info("Creating missing prefix: %s", network_prefix)

                        # Import here to avoid circular dependency
                        from .prefix_manager import PrefixManager

                        prefix_manager = PrefixManager(
                            self.nautobot, self.network_resolver, self.metadata_resolver
                        )

                        # Create the prefix using ensure_prefix_exists
                        # Use the namespace_id directly since we already have it as UUID
                        await prefix_manager.ensure_prefix_exists(
                            prefix=network_prefix,
                            namespace=namespace_id,  # Pass UUID directly
                            status="active",
                            prefix_type="network",
                            description=f"Auto-created for IP {ip_address}",
                        )

                        logger.info(
                            "Successfully created prefix %s, retrying IP creation...",
                            network_prefix,
                        )

                        # Retry IP creation
                        ip_create_result = await self.nautobot.rest_request(
                            endpoint="ipam/ip-addresses/?format=json",
                            method="POST",
                            data=ip_create_data,
                        )

                        ip_id = ip_create_result["id"]
                        logger.info(
                            "Created IP address after prefix creation: %s", ip_id
                        )
                        return ip_id

                    except (ValueError, NautobotAPIError) as prefix_error:
                        logger.error(
                            "Failed to auto-create prefix for %s: %s",
                            ip_address,
                            prefix_error,
                        )
                        raise NautobotAPIError(
                            f"Failed to create IP {ip_address} and could not auto-create prefix: {prefix_error}"
                        ) from prefix_error
                else:
                    # User has disabled automatic prefix creation - stop and raise clear error
                    logger.error(
                        "IP creation failed: No suitable parent prefix exists for %s. Automatic prefix creation is disabled. Error: %s",
                        ip_address,
                        error_message,
                    )
                    raise NautobotAPIError(
                        f"Cannot create IP address {ip_address}: No suitable parent prefix exists. "
                        f"Please either create the parent prefix manually or enable automatic prefix creation in the form."
                    ) from e
            else:
                # Re-raise the original error if not a handled error type
                raise

    async def assign_ip_to_interface(
        self, ip_id: str, interface_id: str, is_primary: bool = False
    ) -> dict:
        """
        Assign IP address to interface using IP-to-Interface association.

        Args:
            ip_id: IP address UUID
            interface_id: Interface UUID
            is_primary: Whether this is the primary IP for the device

        Returns:
            Association result dict

        Raises:
            Exception: If assignment fails
        """
        logger.info("Assigning IP %s to interface %s", ip_id, interface_id)

        # Check if association already exists
        check_endpoint = f"ipam/ip-address-to-interface/?ip_address={ip_id}&interface={interface_id}&format=json"
        existing_associations = await self.nautobot.rest_request(
            endpoint=check_endpoint, method="GET"
        )

        if existing_associations and existing_associations.get("count", 0) > 0:
            logger.info("IP-to-Interface association already exists")
            return existing_associations["results"][0]

        # Create new association
        logger.info("Creating new IP-to-Interface association")
        association_data = {
            "ip_address": ip_id,
            "interface": interface_id,
            "is_primary": is_primary,
        }

        association_result = await self.nautobot.rest_request(
            endpoint="ipam/ip-address-to-interface/?format=json",
            method="POST",
            data=association_data,
        )

        logger.info("Created IP-to-Interface association: %s", association_result["id"])
        return association_result
