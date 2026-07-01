"""
Device Common Service - Unified facade for device operations.

This service provides a clean, stable API for device operations by coordinating
multiple specialized components (resolvers, managers, utilities). It simplifies
dependency management for consumers while maintaining the modular backend architecture.

The facade delegates to specialized modules:
- resolvers/ - Read-only lookups (Device, Metadata, Network)
- managers/ - Create/update operations (IP, Interface, Prefix, Device)
- common/ - Pure utility functions (validators, utils, exceptions)

For most device operations, use this facade. For specialized use cases that need
fine-grained control, you can import resolvers/managers directly.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from services.nautobot import NautobotService
from services.nautobot.common.exceptions import (
    handle_already_exists_error,
    is_duplicate_error,
)
from services.nautobot.common.utils import (
    extract_nested_value,
    flatten_nested_fields,
    normalize_tags,
    prepare_update_data,
)
from services.nautobot.common.validators import (
    is_valid_uuid,
    validate_ip_address,
    validate_mac_address,
    validate_required_fields,
)
from services.nautobot.managers import (
    DeviceManager,
    InterfaceManager,
    IPManager,
    PrefixManager,
)
from services.nautobot.resolvers import (
    DeviceResolver,
    MetadataResolver,
    NetworkResolver,
)

logger = logging.getLogger(__name__)


class DeviceCommonService:
    """
    Unified facade for device operations in Nautobot.

    This facade coordinates multiple specialized components to provide a
    cohesive API for device management. It handles dependency wiring and
    provides convenient access to all device-related operations.

    Components:
    - DeviceResolver: Device and device-type resolution
    - MetadataResolver: Status, role, platform, location resolution
    - NetworkResolver: IP, interface, namespace, prefix resolution
    - DeviceManager: Device-specific operations
    - InterfaceManager: Interface lifecycle management
    - IPManager: IP address operations
    - PrefixManager: Prefix operations

    Usage:
        service = DeviceCommonService(nautobot_service)
        device_id = await service.resolve_device_by_name("router1")
        ip_id = await service.ensure_ip_address_exists("10.0.0.1/24", namespace_id)
    """

    def __init__(self, nautobot_service: NautobotService):
        """
        Initialize the common service with lazy-loaded components.

        Components (resolvers and managers) are instantiated on first access
        to avoid overhead when only a subset of functionality is needed.

        Args:
            nautobot_service: NautobotService instance for API calls
        """
        self.nautobot = nautobot_service

        # Lazy-loaded resolvers (instantiated on first access)
        self._device_resolver = None
        self._metadata_resolver = None
        self._network_resolver = None

        # Lazy-loaded managers (instantiated on first access)
        self._ip_manager = None
        self._prefix_manager = None
        self._interface_manager = None
        self._device_manager = None

    # ========================================================================
    # LAZY-LOADED PROPERTIES (Resolvers & Managers)
    # ========================================================================

    @property
    def device_resolver(self) -> DeviceResolver:
        """Lazy-load DeviceResolver on first access."""
        if self._device_resolver is None:
            self._device_resolver = DeviceResolver(self.nautobot)
        return self._device_resolver

    @property
    def metadata_resolver(self) -> MetadataResolver:
        """Lazy-load MetadataResolver on first access."""
        if self._metadata_resolver is None:
            self._metadata_resolver = MetadataResolver(self.nautobot)
        return self._metadata_resolver

    @property
    def network_resolver(self) -> NetworkResolver:
        """Lazy-load NetworkResolver on first access."""
        if self._network_resolver is None:
            self._network_resolver = NetworkResolver(self.nautobot)
        return self._network_resolver

    @property
    def ip_manager(self) -> IPManager:
        """Lazy-load IPManager on first access."""
        if self._ip_manager is None:
            self._ip_manager = IPManager(
                self.nautobot,
                self.network_resolver,  # Will trigger lazy load if needed
                self.metadata_resolver,
            )
        return self._ip_manager

    @property
    def prefix_manager(self) -> PrefixManager:
        """Lazy-load PrefixManager on first access."""
        if self._prefix_manager is None:
            self._prefix_manager = PrefixManager(
                self.nautobot,
                self.network_resolver,
                self.metadata_resolver,
            )
        return self._prefix_manager

    @property
    def interface_manager(self) -> InterfaceManager:
        """Lazy-load InterfaceManager on first access."""
        if self._interface_manager is None:
            self._interface_manager = InterfaceManager(
                self.nautobot,
                self.network_resolver,
                self.metadata_resolver,
                self.ip_manager,  # Will trigger lazy load if needed
            )
        return self._interface_manager

    @property
    def device_manager(self) -> DeviceManager:
        """Lazy-load DeviceManager on first access."""
        if self._device_manager is None:
            self._device_manager = DeviceManager(
                self.nautobot,
                self.device_resolver,
                self.network_resolver,
            )
        return self._device_manager

    # ========================================================================
    # DEVICE RESOLUTION METHODS (delegated to DeviceResolver)
    # ========================================================================

    async def resolve_device_by_name(self, device_name: str) -> Optional[str]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.resolve_device_by_name(device_name)

    async def resolve_device_by_ip(self, ip_address: str) -> Optional[str]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.resolve_device_by_ip(ip_address)

    async def resolve_device_id(
        self,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        matching_strategy: str = "exact",
    ) -> Optional[str]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.resolve_device_id(
            device_id, device_name, ip_address, matching_strategy=matching_strategy
        )

    async def find_interface_with_ip(
        self, device_name: str, ip_address: str
    ) -> Optional[Tuple[str, str]]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.find_interface_with_ip(
            device_name, ip_address
        )

    async def resolve_device_type_id(
        self, model: str, manufacturer: Optional[str] = None
    ) -> Optional[str]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.resolve_device_type_id(model, manufacturer)

    async def get_device_type_display(self, device_type_id: str) -> Optional[str]:
        """Delegate to DeviceResolver."""
        return await self.device_resolver.get_device_type_display(device_type_id)

    # ========================================================================
    # METADATA RESOLUTION METHODS (delegated to MetadataResolver)
    # ========================================================================

    async def resolve_status_id(
        self, status_name: str, content_type: str = "dcim.device"
    ) -> str:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.resolve_status_id(status_name, content_type)

    async def resolve_role_id(self, role_name: str) -> Optional[str]:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.resolve_role_id(role_name)

    async def resolve_platform_id(self, platform_name: str) -> Optional[str]:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.resolve_platform_id(platform_name)

    async def get_platform_name(self, platform_id: str) -> Optional[str]:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.get_platform_name(platform_id)

    async def resolve_location_id(self, location_name: str) -> Optional[str]:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.resolve_location_id(location_name)

    async def resolve_rack_id(
        self, rack_name: str, location: Optional[str] = None
    ) -> Optional[str]:
        """Delegate to MetadataResolver."""
        return await self.metadata_resolver.resolve_rack_id(
            rack_name, location=location
        )

    # ========================================================================
    # NETWORK RESOLUTION METHODS (delegated to NetworkResolver)
    # ========================================================================

    async def resolve_namespace_id(self, namespace_name: str) -> str:
        """Delegate to NetworkResolver."""
        return await self.network_resolver.resolve_namespace_id(namespace_name)

    async def resolve_ip_address(
        self, ip_address: str, namespace_id: str
    ) -> Optional[str]:
        """Delegate to NetworkResolver."""
        return await self.network_resolver.resolve_ip_address(ip_address, namespace_id)

    async def resolve_interface_by_name(
        self, device_id: str, interface_name: str
    ) -> Optional[str]:
        """Delegate to NetworkResolver."""
        return await self.network_resolver.resolve_interface_by_name(
            device_id, interface_name
        )

    # ========================================================================
    # VALIDATION METHODS (pure functions from common.validators)
    # ========================================================================

    def validate_required_fields(
        self, data: Dict[str, Any], required_fields: List[str]
    ) -> None:
        """Delegate to validators.validate_required_fields."""
        return validate_required_fields(data, required_fields)

    def validate_ip_address(self, ip: str) -> bool:
        """Delegate to validators.validate_ip_address."""
        return validate_ip_address(ip)

    def validate_mac_address(self, mac: str) -> bool:
        """Delegate to validators.validate_mac_address."""
        return validate_mac_address(mac)

    def _is_valid_uuid(self, uuid_str: str) -> bool:
        """Delegate to validators.is_valid_uuid."""
        return is_valid_uuid(uuid_str)

    # ========================================================================
    # DATA PROCESSING METHODS (pure functions from common.utils)
    # ========================================================================

    def flatten_nested_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to utils.flatten_nested_fields."""
        return flatten_nested_fields(data)

    def extract_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Delegate to utils.extract_nested_value."""
        return extract_nested_value(data, path)

    def normalize_tags(self, tags: Any) -> List[str]:
        """Delegate to utils.normalize_tags."""
        return normalize_tags(tags)

    def prepare_update_data(
        self,
        row: Dict[str, str],
        headers: List[str],
        excluded_fields: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, str]], Optional[str]]:
        """Delegate to utils.prepare_update_data."""
        return prepare_update_data(row, headers, excluded_fields)

    # ========================================================================
    # IP ADDRESS METHODS (delegated to IPManager)
    # ========================================================================

    async def ensure_ip_address_exists(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str = "active",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
        **kwargs,
    ) -> str:
        """Delegate to IPManager."""
        return await self.ip_manager.ensure_ip_address_exists(
            ip_address,
            namespace_id,
            status_name,
            add_prefixes_automatically,
            use_assigned_ip_if_exists,
            **kwargs,
        )

    async def assign_ip_to_interface(
        self, ip_id: str, interface_id: str, is_primary: bool = False
    ) -> dict:
        """Delegate to IPManager."""
        return await self.ip_manager.assign_ip_to_interface(
            ip_id, interface_id, is_primary
        )

    # ========================================================================
    # PREFIX METHODS (delegated to PrefixManager)
    # ========================================================================

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
        """Delegate to PrefixManager."""
        return await self.prefix_manager.ensure_prefix_exists(
            prefix, namespace, status, prefix_type, location, description, **kwargs
        )

    # ========================================================================
    # INTERFACE METHODS (delegated to InterfaceManager)
    # ========================================================================

    async def ensure_interface_exists(
        self,
        device_id: str,
        interface_name: str,
        interface_type: str = "virtual",
        interface_status: str = "active",
        **kwargs,
    ) -> str:
        """Delegate to InterfaceManager."""
        return await self.interface_manager.ensure_interface_exists(
            device_id, interface_name, interface_type, interface_status, **kwargs
        )

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
        """Delegate to InterfaceManager."""
        return await self.interface_manager.ensure_interface_with_ip(
            device_id,
            ip_address,
            interface_name,
            interface_type,
            interface_status,
            ip_namespace,
            add_prefixes_automatically,
            use_assigned_ip_if_exists,
        )

    async def update_interface_ip(
        self,
        device_id: str,
        device_name: str,
        old_ip: Optional[str],
        new_ip: str,
        namespace: str,
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
    ) -> str:
        """Delegate to InterfaceManager."""
        return await self.interface_manager.update_interface_ip(
            device_id,
            device_name,
            old_ip,
            new_ip,
            namespace,
            add_prefixes_automatically,
            use_assigned_ip_if_exists,
        )

    # ========================================================================
    # DEVICE OPERATIONS (delegated to DeviceManager)
    # ========================================================================

    async def get_device_details(
        self, device_id: str, depth: int = 0
    ) -> Dict[str, Any]:
        """Delegate to DeviceManager."""
        return await self.device_manager.get_device_details(device_id, depth)

    async def extract_primary_ip_address(
        self, device_data: Dict[str, Any]
    ) -> Optional[str]:
        """Delegate to DeviceManager."""
        return await self.device_manager.extract_primary_ip_address(device_data)

    async def assign_primary_ip_to_device(
        self, device_id: str, ip_address_id: str
    ) -> bool:
        """Delegate to DeviceManager."""
        return await self.device_manager.assign_primary_ip_to_device(
            device_id, ip_address_id
        )

    async def verify_device_updates(
        self,
        device_id: str,
        expected_updates: Dict[str, Any],
        actual_device: Dict[str, Any],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Delegate to DeviceManager."""
        return await self.device_manager.verify_device_updates(
            device_id, expected_updates, actual_device
        )

    # ========================================================================
    # ERROR HANDLING (delegated to common.exceptions)
    # ========================================================================

    def is_duplicate_error(self, error: Exception) -> bool:
        """Delegate to exceptions.is_duplicate_error."""
        return is_duplicate_error(error)

    def handle_already_exists_error(
        self, error: Exception, resource_type: str
    ) -> Dict[str, Any]:
        """Delegate to exceptions.handle_already_exists_error."""
        return handle_already_exists_error(error, resource_type)
