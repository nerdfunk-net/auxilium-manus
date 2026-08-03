"""
Interface lifecycle manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver
    from .ip_manager import IPManager

logger = logging.getLogger(__name__)


class InterfaceManager:
    """Manager for interface lifecycle operations."""

    def __init__(
        self,
        nautobot_service: NautobotService,
        network_resolver: NetworkResolver,
        metadata_resolver: MetadataResolver,
        ip_manager: IPManager,
    ):
        """
        Initialize the interface manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            network_resolver: NetworkResolver instance for resolution
            metadata_resolver: MetadataResolver instance for status resolution
            ip_manager: IPManager instance for IP operations
        """
        self.nautobot = nautobot_service
        self.network_resolver = network_resolver
        self.metadata_resolver = metadata_resolver
        self.ip_manager = ip_manager

    async def ensure_interface_exists(
        self,
        device_id: str,
        interface_name: str,
        interface_type: str = "virtual",
        interface_status: str = "active",
        **kwargs,
    ) -> str:
        """
        Ensure interface exists on device.

        If interface already exists, returns its UUID.
        If not, creates it and returns the new UUID.

        Args:
            device_id: Device UUID
            interface_name: Name of the interface
            interface_type: Type of interface (default: "virtual")
            interface_status: Status name for the interface (default: "active")
            **kwargs: Additional fields for interface creation

        Returns:
            Interface UUID

        Raises:
            Exception: If creation fails and interface doesn't exist
        """
        logger.info("Ensuring interface exists: %s on device %s", interface_name, device_id)

        # Check if interface already exists
        interfaces_endpoint = (
            f"dcim/interfaces/?device_id={device_id}&name={interface_name}&format=json"
        )
        interfaces_result = await self.nautobot.rest_request(
            endpoint=interfaces_endpoint, method="GET"
        )

        if interfaces_result and interfaces_result.get("count", 0) > 0:
            existing_interface = interfaces_result["results"][0]
            logger.info("Interface already exists: %s", existing_interface["id"])
            return existing_interface["id"]

        # Interface doesn't exist, create it
        logger.info("Creating new interface: %s", interface_name)

        # Resolve status to UUID
        status_id = await self.metadata_resolver.resolve_status_id(
            interface_status, content_type="dcim.interface"
        )

        interface_data = {
            "device": device_id,
            "name": interface_name,
            "type": interface_type,
            "status": status_id,
            **kwargs,  # Additional fields from caller
        }

        interface_result = await self.nautobot.rest_request(
            endpoint="dcim/interfaces/?format=json", method="POST", data=interface_data
        )

        interface_id = interface_result["id"]
        logger.info("Created interface: %s", interface_id)
        return interface_id

    async def ensure_interface_with_ip(
        self,
        device_id: str,
        ip_address: str,
        interface_name: str = "Loopback",
        interface_type: str = "virtual",
        interface_status: str = "active",
        ip_namespace: str = "Global",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
    ) -> str:
        """
        Ensure an interface exists with the specified IP address.

        High-level helper that combines multiple operations:
        1. Ensures IP address exists in IPAM
        2. Ensures interface exists on device
        3. Assigns IP to interface

        Args:
            device_id: Device UUID
            ip_address: IP address in CIDR format
            interface_name: Interface name (default: "Loopback")
            interface_type: Interface type (default: "virtual")
            interface_status: Interface status (default: "active")
            ip_namespace: IP namespace name (default: "Global")
            add_prefixes_automatically: Automatically create missing prefix (default: False)
            use_assigned_ip_if_exists: Use existing IP if it exists with different netmask
                (default: False)

        Returns:
            IP address UUID
        """
        logger.info("Ensuring interface with IP %s for device %s", ip_address, device_id)

        # Resolve namespace
        namespace_id = await self.network_resolver.resolve_namespace_id(ip_namespace)

        # Ensure IP exists (with automatic prefix creation if enabled)
        ip_id = await self.ip_manager.ensure_ip_address_exists(
            ip_address=ip_address,
            namespace_id=namespace_id,
            status_name="active",
            add_prefixes_automatically=add_prefixes_automatically,
            use_assigned_ip_if_exists=use_assigned_ip_if_exists,
        )

        # Ensure interface exists
        interface_id = await self.ensure_interface_exists(
            device_id=device_id,
            interface_name=interface_name,
            interface_type=interface_type,
            interface_status=interface_status,
        )

        # Assign IP to interface
        await self.ip_manager.assign_ip_to_interface(
            ip_id=ip_id, interface_id=interface_id, is_primary=True
        )

        logger.info("Successfully ensured interface %s with IP %s", interface_name, ip_address)
        return ip_id

    async def _fallback_ensure_loopback_with_ip(
        self,
        *,
        device_id: str,
        new_ip: str,
        namespace: str,
        add_prefixes_automatically: bool,
        use_assigned_ip_if_exists: bool,
    ) -> str:
        return await self.ensure_interface_with_ip(
            device_id=device_id,
            ip_address=new_ip,
            interface_name="Loopback",
            interface_type="virtual",
            interface_status="active",
            ip_namespace=namespace,
            add_prefixes_automatically=add_prefixes_automatically,
            use_assigned_ip_if_exists=use_assigned_ip_if_exists,
        )

    async def update_interface_ip(
        self,
        device_id: str,
        device_name: str,
        old_ip: str | None,
        new_ip: str,
        namespace: str,
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
    ) -> str:
        """Update an interface IP: find by old_ip, ensure new IP, assign; else create Loopback."""
        from ..resolvers.device_resolver import DeviceResolver

        logger.info(
            "Updating interface IP from %s to %s on device %s",
            old_ip,
            new_ip,
            device_name,
        )

        interface_info = None
        if old_ip:
            interface_info = await DeviceResolver(self.nautobot).find_interface_with_ip(
                device_name=device_name, ip_address=old_ip
            )
            if not interface_info:
                logger.warning(
                    "Could not find interface with IP %s, creating new interface",
                    old_ip,
                )
        else:
            logger.warning("No old IP provided, creating new interface with new IP")

        if not interface_info:
            return await self._fallback_ensure_loopback_with_ip(
                device_id=device_id,
                new_ip=new_ip,
                namespace=namespace,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )

        interface_id, interface_name = interface_info
        logger.info(
            "Found interface '%s' (ID: %s) with IP %s",
            interface_name,
            interface_id,
            old_ip,
        )

        namespace_id = await self.network_resolver.resolve_namespace_id(namespace)
        new_ip_id = await self.ip_manager.ensure_ip_address_exists(
            ip_address=new_ip,
            namespace_id=namespace_id,
            add_prefixes_automatically=add_prefixes_automatically,
            use_assigned_ip_if_exists=use_assigned_ip_if_exists,
        )
        await self.ip_manager.assign_ip_to_interface(ip_id=new_ip_id, interface_id=interface_id)
        logger.info(
            "✓ Successfully updated interface %s from %s to %s",
            interface_name,
            old_ip,
            new_ip,
        )
        return new_ip_id
