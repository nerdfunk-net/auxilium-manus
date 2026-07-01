"""
Device Update Service - Update existing devices in Nautobot.

This service handles updating devices from various sources (CSV, API, UI forms)
with validation, field updates, and interface management.

Based on the workflow from update_devices_task.py but redesigned to:
- Use DeviceCommonService for all shared utilities
- Support flexible input formats and device identification
- Handle primary_ip4 updates with automatic interface creation
- Return detailed results for caller inspection
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from services.nautobot import NautobotService
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.interface_workflow import InterfaceManagerService

logger = logging.getLogger(__name__)


class DeviceUpdateService:
    """
    Service for updating devices in Nautobot.

    Handles the complete workflow:
    1. Resolve device ID from identifier (UUID/name/IP)
    2. Validate and resolve update data
    3. Update device properties via PATCH
    4. Update/create interfaces if needed
    5. Verify updates applied successfully
    """

    def __init__(self, nautobot_service: NautobotService):
        """
        Initialize the update service.

        Args:
            nautobot_service: NautobotService instance for API calls
        """
        self.nautobot = nautobot_service
        self.common = DeviceCommonService(nautobot_service)
        self.interface_manager = InterfaceManagerService(nautobot_service)

    async def update_device(
        self,
        device_identifier: Dict[str, Any],
        update_data: Dict[str, Any],
        interface_config: Optional[Dict[str, str]] = None,
        interfaces: Optional[List[Dict[str, Any]]] = None,
        create_if_missing: bool = False,
        add_prefix: bool = True,
        default_prefix_length: str = "/24",
        matching_strategy: str = "exact",
        rack_location: Optional[str] = None,
        sync_interfaces: bool = False,
    ) -> Dict[str, Any]:
        """
        Update a single device.

        Workflow:
        1. Resolve device UUID from identifier
        2. Validate and resolve update data (names → UUIDs)
        3. Update device properties via PATCH
        4. Update/create interfaces if needed
        5. Verify updates applied

        Args:
            device_identifier: Device identifier dict with at least one of:
                - id: Device UUID
                - name: Device name
                - ip_address: Primary IPv4 address

            update_data: Fields to update, can include:
                - status: Status name or UUID
                - platform: Platform name or UUID
                - role: Role name or UUID
                - location: Location name or UUID
                - device_type: Device type name or UUID
                - serial: Serial number
                - asset_tag: Asset tag
                - tags: List of tag names or comma-separated string
                - custom_fields: Dict of custom field values
                - primary_ip4: IP address (will create interface if needed)
                - Any other device field

            interface_config: Optional interface config for primary_ip4 updates (legacy):
                {
                    "name": "Loopback0",        # Default: "Loopback"
                    "type": "virtual",          # Default: "virtual"
                    "status": "active",         # Default: "active"
                }

            interfaces: Optional list of interfaces to create/update:
                [
                    {
                        "name": "Ethernet0/0",
                        "type": "1000base-t",
                        "status": "active",
                        "ip_address": "192.168.1.1/24",
                        "namespace": "Global",
                        "is_primary_ipv4": True,
                        "enabled": True,
                        "description": "...",
                        ...
                    },
                    ...
                ]

            create_if_missing: If True, create device if not found (uses DeviceImportService)

        Returns:
            {
                "success": True,  # Always True (exceptions raised on failure)
                "device_id": str,
                "device_name": str,
                "message": str,
                "updated_fields": List[str],
                "warnings": List[str],
                "interfaces_created": int,
                "interfaces_failed": int,
                "details": {
                    "before": {...},  # Device state before update
                    "after": {...},   # Device state after update
                    "changes": {...}  # Fields that changed
                }
            }

        Raises:
            ValueError: If device not found and create_if_missing=False, or validation fails
            NautobotAPIError: If Nautobot API request fails
            Exception: If update fails for any other reason
        """
        logger.info("Starting device update for: %s", device_identifier)

        warnings = []
        details = {
            "before": None,
            "after": None,
            "changes": {},
        }

        try:
            # Step 1: Resolve device ID
            logger.info("Step 1: Resolving device ID")
            device_id, device_name = await self._resolve_device_id(
                device_identifier, matching_strategy=matching_strategy
            )

            if not device_id:
                if create_if_missing:
                    # TODO: Call DeviceImportService to create device
                    # For now, raise error
                    raise ValueError(
                        "Device not found and create_if_missing not yet implemented"
                    )
                else:
                    raise ValueError(
                        f"Device not found with identifier: {device_identifier}"
                    )

            # Get device state before update (with depth=1 to get full primary_ip4 object)
            details["before"] = await self.common.get_device_details(
                device_id=device_id, depth=1
            )

            # Extract current primary_ip4 for updating existing interface
            current_primary_ip4 = await self.common.extract_primary_ip_address(
                details["before"]
            )

            # Step 2: Validate and resolve update data
            logger.info("Step 2: Validating and resolving update data")
            validated_data, ip_namespace = await self.validate_update_data(
                device_id, update_data, interface_config, rack_location=rack_location
            )

            # Only return early if BOTH validated_data AND interfaces are empty
            if not validated_data and not interfaces:
                logger.info(
                    "No fields to update and no interfaces for device %s", device_name
                )
                return {
                    "success": True,
                    "device_id": device_id,
                    "device_name": device_name,
                    "message": f"Device '{device_name}' - no fields to update and no interfaces",
                    "updated_fields": [],
                    "warnings": ["No fields to update and no interfaces"],
                    "details": details,
                }

            # Log what we're going to process
            if not validated_data and interfaces:
                logger.info(
                    "No device fields to update, but processing %s interface(s)",
                    len(interfaces),
                )

            # Step 3: Update device properties (if any)
            updated_fields = []
            if validated_data:
                logger.info(
                    "Step 3: Updating device %s with %s field(s)",
                    device_name,
                    len(validated_data),
                )
                updated_fields = await self._update_device_properties(
                    device_id=device_id,
                    validated_data=validated_data,
                    interface_config=interface_config,
                    ip_namespace=ip_namespace,
                    device_name=device_name,
                    current_primary_ip4=current_primary_ip4,
                )
            else:
                logger.info(
                    "Step 3: Skipping device property updates (no fields to update)"
                )

            # Step 3.5: Create/update interfaces if provided
            interfaces_created = 0
            interfaces_updated = 0
            interfaces_failed = 0
            if interfaces:
                logger.info(
                    "Step 3.5: Creating/updating %s interface(s)", len(interfaces)
                )
                logger.info("Prefix auto-creation enabled: %s", add_prefix)
                interface_result = (
                    await self.interface_manager.update_device_interfaces(
                        device_id=device_id,
                        interfaces=interfaces,
                        add_prefixes_automatically=add_prefix,
                        sync_interfaces=sync_interfaces,
                    )
                )
                interfaces_created = interface_result.interfaces_created
                interfaces_updated = interface_result.interfaces_updated
                interfaces_failed = interface_result.interfaces_failed
                warnings.extend(interface_result.warnings)
                logger.info(
                    "Interface update complete: %s created, %s updated, %s failed",
                    interfaces_created,
                    interfaces_updated,
                    interfaces_failed,
                )

            # Get device state after update
            details["after"] = await self.common.get_device_details(
                device_id=device_id, depth=0
            )

            # Track changes
            details["changes"] = {
                field: {
                    "from": details["before"].get(field),
                    "to": details["after"].get(field),
                }
                for field in updated_fields
            }

            # Step 4: Verify updates (optional)
            logger.info("Step 4: Verifying updates")
            verification_passed, mismatches = await self.common.verify_device_updates(
                device_id, validated_data, details["after"]
            )

            if not verification_passed:
                warnings.append("Some updates may not have been applied correctly")
                # Add detailed mismatch info to warnings
                for mismatch in mismatches:
                    warnings.append(
                        f"{mismatch['field']}: expected {mismatch['expected']}, got {mismatch['actual']}"
                    )

            # Success!
            success_message = f"Device '{device_name}' updated successfully"
            if interfaces_created > 0 or interfaces_updated > 0:
                success_message += f" ({interfaces_created} interface(s) created, {interfaces_updated} updated)"

            return {
                "success": True,
                "device_id": device_id,
                "device_name": device_name,
                "message": success_message,
                "updated_fields": updated_fields,
                "warnings": warnings,
                "interfaces_created": interfaces_created,
                "interfaces_updated": interfaces_updated,
                "interfaces_failed": interfaces_failed,
                "details": details,
            }

        except Exception as e:
            error_msg = f"Failed to update device {device_identifier}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            # Re-raise exception - let caller handle HTTP response conversion
            raise

    async def _resolve_device_id(
        self, device_identifier: Dict[str, Any], matching_strategy: str = "exact"
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve device UUID and name from identifier.

        Args:
            device_identifier: Dict with id, name, or ip_address
            matching_strategy: How to match by name - "exact", "contains", "starts_with"

        Returns:
            Tuple of (device_id, device_name)

        Raises:
            ValueError: If no valid identifier provided
        """
        device_id = device_identifier.get("id")
        device_name = device_identifier.get("name")
        ip_address = device_identifier.get("ip_address")

        if not any([device_id, device_name, ip_address]):
            raise ValueError(
                "Device identifier must include at least one of: id, name, ip_address"
            )

        # Use common service to resolve
        resolved_id = await self.common.resolve_device_id(
            device_id=device_id,
            device_name=device_name,
            ip_address=ip_address,
            matching_strategy=matching_strategy,
        )

        if not resolved_id:
            return None, None

        # If we don't have the name yet, fetch it
        if not device_name:
            device_response = await self.nautobot.rest_request(
                endpoint=f"dcim/devices/{resolved_id}/",
                method="GET",
            )
            device_name = device_response.get("name", resolved_id)

        logger.info("Resolved device: %s (%s)", device_name, resolved_id)
        return resolved_id, device_name

    async def validate_update_data(
        self,
        device_id: str,
        update_data: Dict[str, Any],
        interface_config: Optional[Dict[str, str]] = None,
        rack_location: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Validate update data and resolve all resource names to UUIDs.

        Args:
            device_id: Device UUID (for context)
            update_data: Raw update data dictionary
            interface_config: Optional interface config for primary_ip4

        Returns:
            Tuple of (validated_data dict, ip_namespace str or None)

        Note:
            - Filters out empty values
            - Handles nested fields like "platform.name" → "platform"
            - Resolves all names to UUIDs
            - Normalizes tags to list format
        """
        logger.debug("Validating update data for device %s: %s", device_id, update_data)

        validated = {}
        ip_namespace = None

        for field, value in update_data.items():
            # Skip empty values, but allow explicit None for rack-assignment fields
            # so they can be sent as JSON null to Nautobot (clearing the assignment).
            if value is None and field not in ("rack", "position", "face"):
                continue
            if isinstance(value, str) and not value.strip():
                continue

            # Handle nested fields (e.g., "platform.name" → "platform")
            if "." in field:
                base_field, nested_field = field.rsplit(".", 1)
                field = base_field
                logger.debug(
                    "Flattened nested field: %s.%s → %s", field, nested_field, field
                )

            # Clean string values
            if isinstance(value, str):
                value = value.strip()

            # Handle special fields that need resolution
            if field == "status":
                # Resolve status name to UUID
                if not self.common._is_valid_uuid(value):
                    validated[field] = await self.common.resolve_status_id(
                        value, "dcim.device"
                    )
                else:
                    validated[field] = value

            elif field == "platform":
                # Resolve platform name to UUID
                if not self.common._is_valid_uuid(value):
                    platform_id = await self.common.resolve_platform_id(value)
                    if platform_id:
                        validated[field] = platform_id
                    else:
                        logger.warning(
                            "Platform '%s' not found, will be omitted", value
                        )
                else:
                    validated[field] = value

            elif field == "role":
                # Resolve role name to UUID
                if not self.common._is_valid_uuid(value):
                    role_id = await self.common.resolve_role_id(value)
                    if role_id:
                        validated[field] = role_id
                    else:
                        logger.warning("Role '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "location":
                # Resolve location name to UUID
                if not self.common._is_valid_uuid(value):
                    location_id = await self.common.resolve_location_id(value)
                    if location_id:
                        validated[field] = location_id
                    else:
                        logger.warning(
                            "Location '%s' not found, will be omitted", value
                        )
                else:
                    validated[field] = value

            elif field == "rack":
                # Resolve rack name to UUID, optionally filtered by location.
                # None means explicit clear (send null to Nautobot).
                if value is None:
                    validated[field] = None
                elif not self.common._is_valid_uuid(value):
                    rack_id = await self.common.resolve_rack_id(
                        value, location=rack_location
                    )
                    if rack_id:
                        validated[field] = rack_id
                    else:
                        logger.warning("Rack '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "device_type":
                # Resolve device type name to UUID
                if not self.common._is_valid_uuid(value):
                    device_type_id = await self.common.resolve_device_type_id(value)
                    if device_type_id:
                        validated[field] = device_type_id
                    else:
                        logger.warning(
                            "Device type '%s' not found, will be omitted", value
                        )
                else:
                    validated[field] = value

            elif field == "tags":
                # Normalize tags to list
                validated[field] = self.common.normalize_tags(value)

            elif field == "ip_namespace":
                # Store for later use with primary_ip4
                ip_namespace = value

            elif field == "custom_fields":
                # Ensure custom_fields is a simple dict (Nautobot expects {"field_name": "value"})
                if isinstance(value, dict):
                    validated[field] = value
                else:
                    logger.warning(
                        "Invalid custom_fields format: %s, expected dict", type(value)
                    )

            else:
                # Copy other fields as-is (including primary_ip4, etc.)
                validated[field] = value

        # Rack / position / face consistency check.
        # Nautobot requires "face" whenever "position" is set.  If "position" arrived
        # in the update data but "face" did not (or is empty), clear "position" to
        # avoid the "Must specify rack face when defining rack position" error.
        # Exception: when position is None (explicit clear), both None is intentional.
        if (
            "position" in validated
            and validated.get("position") is not None
            and not validated.get("face")
        ):
            logger.warning(
                "Dropping 'position' from update data because 'face' is not set — "
                "Nautobot requires both fields when specifying a rack position."
            )
            validated.pop("position")

        logger.info("Validation complete, %s fields to update", len(validated))
        logger.debug("Validated data: %s", validated)

        return validated, ip_namespace

    async def _update_device_properties(
        self,
        device_id: str,
        validated_data: Dict[str, Any],
        interface_config: Optional[Dict[str, str]] = None,
        ip_namespace: Optional[str] = None,
        device_name: Optional[str] = None,
        current_primary_ip4: Optional[str] = None,
    ) -> List[str]:
        """
        Update device properties via PATCH request.

        Special handling for primary_ip4:
        - If createOnIpChange=true: Creates new interface with new IP
        - If createOnIpChange=false: Updates existing interface's IP address

        Args:
            device_id: Device UUID
            validated_data: Validated update data with UUIDs
            interface_config: Optional interface config for primary_ip4
            ip_namespace: Optional IP namespace for primary_ip4
            device_name: Device name (required for updating existing interface)
            current_primary_ip4: Current primary IP address (for finding interface to update)

        Returns:
            List of updated field names
        """
        logger.info("Updating device %s via REST API", device_id)
        logger.debug("Update data: %s", validated_data)

        # Make a copy so we don't modify the original
        update_payload = validated_data.copy()
        updated_fields = list(update_payload.keys())

        # Special handling for primary_ip4
        if "primary_ip4" in update_payload:
            primary_ip4 = update_payload["primary_ip4"]
            logger.info("Processing primary_ip4 update: %s", primary_ip4)

            # Use interface config if provided, otherwise use defaults
            if not interface_config:
                interface_config = {
                    "name": "Loopback",
                    "type": "virtual",
                    "status": "active",
                    "mgmt_interface_create_on_ip_change": False,
                }

            # Use namespace if provided, otherwise default to "Global"
            namespace = ip_namespace or "Global"

            # Check if we should create a new interface or update existing
            create_new = interface_config.get(
                "mgmt_interface_create_on_ip_change", False
            )
            logger.info("Create new interface on IP change: %s", create_new)

            # Get add_prefixes_automatically flag (default to False for backward compatibility)
            add_prefixes_automatically = interface_config.get(
                "add_prefixes_automatically", False
            )
            logger.info("Add prefixes automatically: %s", add_prefixes_automatically)

            # Get use_assigned_ip_if_exists flag (default to False for backward compatibility)
            use_assigned_ip_if_exists = interface_config.get(
                "use_assigned_ip_if_exists", False
            )
            logger.info("Use assigned IP if exists: %s", use_assigned_ip_if_exists)

            if create_new:
                # BEHAVIOR 1: Create new interface with new IP (existing behavior)
                logger.info("Creating new interface with new IP address")
                ip_id = await self.common.ensure_interface_with_ip(
                    device_id=device_id,
                    ip_address=primary_ip4,
                    interface_name=interface_config.get("name", "Loopback"),
                    interface_type=interface_config.get("type", "virtual"),
                    interface_status=interface_config.get("status", "active"),
                    ip_namespace=namespace,
                    add_prefixes_automatically=add_prefixes_automatically,
                    use_assigned_ip_if_exists=use_assigned_ip_if_exists,
                )
            else:
                # BEHAVIOR 2: Update existing interface's IP address
                logger.info("Updating existing interface's IP address")
                ip_id = await self.common.update_interface_ip(
                    device_id=device_id,
                    device_name=device_name,
                    old_ip=current_primary_ip4,
                    new_ip=primary_ip4,
                    namespace=namespace,
                    add_prefixes_automatically=add_prefixes_automatically,
                    use_assigned_ip_if_exists=use_assigned_ip_if_exists,
                )

            # Update the payload to use the IP UUID instead of the address string
            update_payload["primary_ip4"] = ip_id
            logger.info("Updated primary_ip4 to use IP UUID: %s", ip_id)

        # PATCH the device
        endpoint = f"dcim/devices/{device_id}/"
        result = await self.nautobot.rest_request(
            endpoint=endpoint,
            method="PATCH",
            data=update_payload,
        )

        # Verify primary_ip4 was set if it was in the update
        if "primary_ip4" in update_payload:
            expected_ip_id = update_payload["primary_ip4"]
            actual_ip = result.get("primary_ip4", {})
            actual_ip_id = (
                actual_ip.get("id") if isinstance(actual_ip, dict) else actual_ip
            )

            if actual_ip_id != expected_ip_id:
                error_msg = (
                    f"Device update verification failed: primary_ip4 mismatch "
                    f"(expected {expected_ip_id}, got {actual_ip_id})"
                )
                logger.error(error_msg)
                logger.error("Full update result: %s", result)
                raise ValueError(error_msg)

            logger.info(
                "✓ Successfully verified device %s primary_ip4 is set to %s",
                device_id,
                expected_ip_id,
            )

        logger.info("Successfully updated device %s", device_id)
        return updated_fields
