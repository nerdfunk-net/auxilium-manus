"""
IP address lifecycle manager.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from services.nautobot.common.rest import rest_query
from services.nautobot.common.validators import is_valid_uuid

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot.api_protocol import NautobotApi

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)


def _is_duplicate_host_error(error_message: str) -> bool:
    return "IP address with this Parent and Host already exists" in error_message


def _is_missing_prefix_error(error_message: str) -> bool:
    return "No suitable parent Prefix" in error_message


def _reference_id(value: object) -> object:
    """A related object arrives as a UUID or as a nested object; compare by its id."""
    return value.get("id") if isinstance(value, dict) else value


def _same_value(key: str, current: Mapping[str, object], value: str) -> bool:
    """Nautobot stores a DNS name in lower case, so its case never counts as a change."""
    stored = _reference_id(current.get(key))
    if key == "dns_name" and isinstance(stored, str):
        return stored.lower() == value.lower()
    return stored == value


class IPManager:
    """Manager for IP address lifecycle operations."""

    def __init__(
        self,
        nautobot_service: NautobotApi,
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

    async def _find_ip_by_address(self, ip_address: str, namespace_id: str) -> str | None:
        ip_search_endpoint = (
            f"ipam/ip-addresses/?"
            f"{rest_query(address=ip_address, namespace=namespace_id, format='json')}"
        )
        ip_result = await self.nautobot.rest_request(endpoint=ip_search_endpoint, method="GET")

        if ip_result and ip_result.get("count", 0) > 0:
            existing_ip = ip_result["results"][0]
            logger.info("IP address already exists: %s", existing_ip["id"])
            return existing_ip["id"]
        return None

    async def _build_ip_create_payload(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str,
        **kwargs,
    ) -> dict:
        status_id = await self.metadata_resolver.resolve_status_id(
            status_name, content_type="ipam.ipaddress"
        )
        return {
            "address": ip_address,
            "status": status_id,
            "namespace": namespace_id,
            **kwargs,
        }

    async def _create_ip_address(self, ip_create_data: dict) -> str:
        ip_create_result = await self.nautobot.rest_request(
            endpoint="ipam/ip-addresses/?format=json",
            method="POST",
            data=ip_create_data,
        )
        ip_id = ip_create_result["id"]
        logger.info("Created IP address: %s", ip_id)
        return ip_id

    async def _find_existing_ip_by_host(self, ip_address: str, namespace_id: str) -> str:
        ip_obj = ipaddress.ip_interface(ip_address)
        host_ip = str(ip_obj.ip)

        logger.info("Searching for existing IP with host address: %s", host_ip)

        ip_search_endpoint = (
            f"ipam/ip-addresses/?"
            f"{rest_query(address=host_ip, namespace=namespace_id, format='json')}"
        )
        existing_ip_result = await self.nautobot.rest_request(
            endpoint=ip_search_endpoint, method="GET"
        )

        if existing_ip_result and existing_ip_result.get("count", 0) > 0:
            existing_ip = existing_ip_result["results"][0]
            logger.info(
                "Found existing IP: %s with UUID %s",
                existing_ip["address"],
                existing_ip["id"],
            )

            if existing_ip_result.get("count", 0) > 1:
                logger.warning(
                    "Multiple IPs found with host %s (%s total), using first: %s",
                    host_ip,
                    existing_ip_result["count"],
                    existing_ip["address"],
                )

            return existing_ip["id"]

        logger.error("Could not find existing IP for host %s", host_ip)
        raise NautobotAPIError(f"IP {host_ip} reported as duplicate but not found in namespace")

    async def _ensure_parent_prefix_and_retry(
        self,
        ip_address: str,
        namespace_id: str,
        ip_create_data: dict,
    ) -> str:
        ip_obj = ipaddress.ip_interface(ip_address)
        network_prefix = str(ip_obj.network)

        logger.info("Creating missing prefix: %s", network_prefix)

        from .prefix_manager import PrefixManager

        prefix_manager = PrefixManager(self.nautobot, self.network_resolver, self.metadata_resolver)

        await prefix_manager.ensure_prefix_exists(
            prefix=network_prefix,
            namespace=namespace_id,
            status="active",
            prefix_type="network",
            description=f"Auto-created for IP {ip_address}",
        )

        logger.info(
            "Successfully created prefix %s, retrying IP creation...",
            network_prefix,
        )

        ip_id = await self._create_ip_address(ip_create_data)
        logger.info("Created IP address after prefix creation: %s", ip_id)
        return ip_id

    async def _handle_ip_create_error(
        self,
        *,
        error: NautobotAPIError,
        ip_address: str,
        namespace_id: str,
        ip_create_data: dict,
        add_prefixes_automatically: bool,
        use_assigned_ip_if_exists: bool,
    ) -> str:
        error_message = str(error)

        if _is_duplicate_host_error(error_message) and use_assigned_ip_if_exists:
            logger.warning(
                "IP creation failed: IP %s already exists with different netmask. "
                "Attempting to find existing IP...",
                ip_address,
            )
            try:
                return await self._find_existing_ip_by_host(ip_address, namespace_id)
            except (ValueError, NautobotAPIError, KeyError) as lookup_error:
                logger.error(
                    "Failed to find existing IP for %s: %s",
                    ip_address,
                    lookup_error,
                )
                raise NautobotAPIError(
                    f"Failed to create IP {ip_address} and could not find "
                    f"existing IP: {lookup_error}"
                ) from lookup_error

        if not _is_missing_prefix_error(error_message):
            raise error

        if add_prefixes_automatically:
            logger.warning(
                "IP creation failed due to missing prefix. "
                "Attempting to create prefix automatically..."
            )
            try:
                return await self._ensure_parent_prefix_and_retry(
                    ip_address, namespace_id, ip_create_data
                )
            except (ValueError, NautobotAPIError) as prefix_error:
                logger.error(
                    "Failed to auto-create prefix for %s: %s",
                    ip_address,
                    prefix_error,
                )
                raise NautobotAPIError(
                    f"Failed to create IP {ip_address} and could not "
                    f"auto-create prefix: {prefix_error}"
                ) from prefix_error

        logger.error(
            "IP creation failed: No suitable parent prefix exists for %s. "
            "Automatic prefix creation is disabled. Error: %s",
            ip_address,
            error_message,
        )
        raise NautobotAPIError(
            f"Cannot create IP address {ip_address}: No suitable parent "
            "prefix exists. Please either create the parent prefix manually "
            "or enable automatic prefix creation in the form."
        ) from error

    async def ensure_ip_address_exists(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str = "active",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
        **kwargs,
    ) -> str:
        """Return existing IP UUID or create the address (optionally auto-creating prefix)."""
        logger.info("Ensuring IP address exists: %s", ip_address)

        existing_id = await self._find_ip_by_address(ip_address, namespace_id)
        if existing_id is not None:
            return existing_id

        logger.info("Creating new IP address: %s", ip_address)
        ip_create_data = await self._build_ip_create_payload(
            ip_address, namespace_id, status_name, **kwargs
        )
        try:
            return await self._create_ip_address(ip_create_data)
        except NautobotAPIError as e:
            return await self._handle_ip_create_error(
                error=e,
                ip_address=ip_address,
                namespace_id=namespace_id,
                ip_create_data=ip_create_data,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )

    async def update_ip_address(
        self,
        ip_id: str,
        fields: Mapping[str, str],
        *,
        find_parent: Callable[[str], Awaitable[str]] | None = None,
    ) -> bool:
        """
        Update an existing IP address; only the values that differ are sent.

        Nautobot ignores ``namespace`` on an existing address (it answers 200 and keeps the
        parent), so a namespace move is a change of ``parent``: ``find_parent`` receives the
        host address and returns the id of the prefix in the target namespace to move to.

        Args:
            ip_id: IP address UUID
            fields: Nautobot REST fields to set (``status`` and ``role`` as ids, ``type``,
                ``dns_name`` and ``description`` as text)
            find_parent: Optional lookup of the target parent prefix id for a namespace move

        Returns:
            True when a PATCH was sent, False when the address already had every value.

        Raises:
            ValueError: If ``ip_id`` is not a UUID.
            NautobotNotFoundError: If the address does not exist.
            NautobotAPIError: If Nautobot refuses the change.
        """
        if not is_valid_uuid(ip_id.lower()):
            raise ValueError("ip_id is not a Nautobot UUID")
        endpoint = f"ipam/ip-addresses/{ip_id}/?format=json"
        current = await self.nautobot.rest_request(endpoint=endpoint, method="GET")
        changes = {
            key: value for key, value in fields.items() if not _same_value(key, current, value)
        }
        if find_parent is not None:
            parent_id = await find_parent(str(current.get("host") or ""))
            if _reference_id(current.get("parent")) != parent_id:
                changes["parent"] = parent_id
        if not changes:
            logger.info("IP address %s already has the requested values", ip_id)
            return False

        logger.info("Updating IP address %s fields=%s", ip_id, sorted(changes))
        await self.nautobot.rest_request(endpoint=endpoint, method="PATCH", data=changes)
        return True

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
        check_endpoint = (
            f"ipam/ip-address-to-interface/?"
            f"{rest_query(ip_address=ip_id, interface=interface_id, format='json')}"
        )
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
