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
from typing import Any

from services.nautobot import NautobotService
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.interface_workflow import InterfaceManagerService

logger = logging.getLogger(__name__)

_RACK_CLEARABLE_FIELDS = frozenset({"rack", "position", "face"})


def _prepare_update_field(field: str, value: Any) -> tuple[str, Any] | None:
    if value is None and field not in _RACK_CLEARABLE_FIELDS:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    if "." in field:
        base_field, nested_field = field.rsplit(".", 1)
        field = base_field
        logger.debug("Flattened nested field: %s.%s → %s", field, nested_field, field)

    if isinstance(value, str):
        value = value.strip()

    return field, value


def _enforce_rack_position_face(validated: dict[str, Any]) -> None:
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


def _default_primary_ip_interface_config() -> dict[str, Any]:
    return {
        "name": "Loopback",
        "type": "virtual",
        "status": "active",
        "mgmt_interface_create_on_ip_change": False,
    }


def _verify_primary_ip4_applied(
    *,
    device_id: str,
    expected_ip_id: str,
    result: dict[str, Any],
) -> None:
    actual_ip = result.get("primary_ip4", {})
    actual_ip_id = actual_ip.get("id") if isinstance(actual_ip, dict) else actual_ip

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

    def _empty_update_result(
        self,
        *,
        device_id: str,
        device_name: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "success": True,
            "device_id": device_id,
            "device_name": device_name,
            "message": f"Device '{device_name}' - no fields to update and no interfaces",
            "updated_fields": [],
            "warnings": ["No fields to update and no interfaces"],
            "details": details,
        }

    async def _apply_interface_updates(
        self,
        *,
        device_id: str,
        interfaces: list[dict[str, Any]],
        add_prefix: bool,
        sync_interfaces: bool,
        warnings: list[str],
    ) -> tuple[int, int, int]:
        logger.info("Step 3.5: Creating/updating %s interface(s)", len(interfaces))
        logger.info("Prefix auto-creation enabled: %s", add_prefix)
        interface_result = await self.interface_manager.update_device_interfaces(
            device_id=device_id,
            interfaces=interfaces,
            add_prefixes_automatically=add_prefix,
            sync_interfaces=sync_interfaces,
        )
        warnings.extend(interface_result.warnings)
        logger.info(
            "Interface update complete: %s created, %s updated, %s failed",
            interface_result.interfaces_created,
            interface_result.interfaces_updated,
            interface_result.interfaces_failed,
        )
        return (
            interface_result.interfaces_created,
            interface_result.interfaces_updated,
            interface_result.interfaces_failed,
        )

    def _compute_field_changes(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        updated_fields: list[str],
    ) -> dict[str, dict[str, Any]]:
        return {
            field: {
                "from": before.get(field),
                "to": after.get(field),
            }
            for field in updated_fields
        }

    async def _collect_verification_warnings(
        self,
        *,
        device_id: str,
        validated_data: dict[str, Any],
        after_state: dict[str, Any],
        warnings: list[str],
    ) -> None:
        logger.info("Step 4: Verifying updates")
        verification_passed, mismatches = await self.common.verify_device_updates(
            device_id, validated_data, after_state
        )

        if not verification_passed:
            warnings.append("Some updates may not have been applied correctly")
            for mismatch in mismatches:
                warnings.append(
                    f"{mismatch['field']}: expected {mismatch['expected']}, "
                    f"got {mismatch['actual']}"
                )

    def _success_update_result(
        self,
        *,
        device_id: str,
        device_name: str,
        updated_fields: list[str],
        warnings: list[str],
        interfaces_created: int,
        interfaces_updated: int,
        interfaces_failed: int,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        success_message = f"Device '{device_name}' updated successfully"
        if interfaces_created > 0 or interfaces_updated > 0:
            success_message += (
                f" ({interfaces_created} interface(s) created, {interfaces_updated} updated)"
            )

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

    async def _resolve_device_for_update(
        self,
        device_identifier: dict[str, Any],
        *,
        matching_strategy: str,
    ) -> tuple[str, str]:
        logger.info("Step 1: Resolving device ID")
        device_id, device_name = await self._resolve_device_id(
            device_identifier, matching_strategy=matching_strategy
        )
        if device_id:
            return device_id, device_name or ""
        raise ValueError(f"Device not found with identifier: {device_identifier}")

    async def _apply_property_updates(
        self,
        *,
        device_id: str,
        device_name: str,
        validated_data: dict[str, Any],
        interface_config: dict[str, str] | None,
        ip_namespace: str | None,
        current_primary_ip4: str | None,
    ) -> list[str]:
        if not validated_data:
            logger.info("Step 3: Skipping device property updates (no fields to update)")
            return []
        logger.info(
            "Step 3: Updating device %s with %s field(s)",
            device_name,
            len(validated_data),
        )
        return await self._update_device_properties(
            device_id=device_id,
            validated_data=validated_data,
            interface_config=interface_config,
            ip_namespace=ip_namespace,
            device_name=device_name,
            current_primary_ip4=current_primary_ip4,
        )

    async def _finalize_device_update(
        self,
        *,
        device_id: str,
        device_name: str,
        validated_data: dict[str, Any],
        updated_fields: list[str],
        warnings: list[str],
        interfaces_created: int,
        interfaces_updated: int,
        interfaces_failed: int,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        details["after"] = await self.common.get_device_details(device_id=device_id, depth=0)
        details["changes"] = self._compute_field_changes(
            details["before"], details["after"], updated_fields
        )
        await self._collect_verification_warnings(
            device_id=device_id,
            validated_data=validated_data,
            after_state=details["after"],
            warnings=warnings,
        )
        return self._success_update_result(
            device_id=device_id,
            device_name=device_name,
            updated_fields=updated_fields,
            warnings=warnings,
            interfaces_created=interfaces_created,
            interfaces_updated=interfaces_updated,
            interfaces_failed=interfaces_failed,
            details=details,
        )

    async def update_device(
        self,
        device_identifier: dict[str, Any],
        update_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        interfaces: list[dict[str, Any]] | None = None,
        add_prefix: bool = True,
        default_prefix_length: str = "/24",
        matching_strategy: str = "exact",
        rack_location: str | None = None,
        sync_interfaces: bool = False,
    ) -> dict[str, Any]:
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
            ValueError: If device not found, or validation fails
            NautobotAPIError: If Nautobot API request fails
            Exception: If update fails for any other reason
        """
        logger.info("Starting device update for: %s", device_identifier)
        warnings: list[str] = []
        details: dict[str, Any] = {"before": None, "after": None, "changes": {}}
        try:
            device_id, device_name = await self._resolve_device_for_update(
                device_identifier,
                matching_strategy=matching_strategy,
            )
            details["before"] = await self.common.get_device_details(device_id=device_id, depth=1)
            current_primary_ip4 = await self.common.extract_primary_ip_address(details["before"])

            logger.info("Step 2: Validating and resolving update data")
            validated_data, ip_namespace = await self.validate_update_data(
                device_id, update_data, interface_config, rack_location=rack_location
            )
            if not validated_data and not interfaces:
                logger.info("No fields to update and no interfaces for device %s", device_name)
                return self._empty_update_result(
                    device_id=device_id, device_name=device_name, details=details
                )
            if not validated_data and interfaces:
                logger.info(
                    "No device fields to update, but processing %s interface(s)",
                    len(interfaces),
                )

            updated_fields = await self._apply_property_updates(
                device_id=device_id,
                device_name=device_name,
                validated_data=validated_data,
                interface_config=interface_config,
                ip_namespace=ip_namespace,
                current_primary_ip4=current_primary_ip4,
            )
            interfaces_created = interfaces_updated = interfaces_failed = 0
            if interfaces:
                interfaces_created, interfaces_updated, interfaces_failed = (
                    await self._apply_interface_updates(
                        device_id=device_id,
                        interfaces=interfaces,
                        add_prefix=add_prefix,
                        sync_interfaces=sync_interfaces,
                        warnings=warnings,
                    )
                )
            return await self._finalize_device_update(
                device_id=device_id,
                device_name=device_name,
                validated_data=validated_data,
                updated_fields=updated_fields,
                warnings=warnings,
                interfaces_created=interfaces_created,
                interfaces_updated=interfaces_updated,
                interfaces_failed=interfaces_failed,
                details=details,
            )
        except Exception as e:
            logger.error(
                "Failed to update device %s: %s", device_identifier, e, exc_info=True
            )
            raise

    async def _resolve_device_id(
        self, device_identifier: dict[str, Any], matching_strategy: str = "exact"
    ) -> tuple[str | None, str | None]:
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
            raise ValueError("Device identifier must include at least one of: id, name, ip_address")

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

    async def _resolve_update_field(
        self,
        field: str,
        value: Any,
        *,
        rack_location: str | None,
    ) -> tuple[str, ...]:
        if field == "status":
            if not self.common._is_valid_uuid(value):
                resolved = await self.common.resolve_status_id(value, "dcim.device")
                return ("set", field, resolved)
            return ("set", field, value)

        if field == "platform":
            return await self._resolve_named_id_field(
                field, value, self.common.resolve_platform_id, "Platform"
            )

        if field == "role":
            return await self._resolve_named_id_field(
                field, value, self.common.resolve_role_id, "Role"
            )

        if field == "location":
            return await self._resolve_named_id_field(
                field, value, self.common.resolve_location_id, "Location"
            )

        if field == "rack":
            if value is None:
                return ("set", field, None)
            if not self.common._is_valid_uuid(value):
                rack_id = await self.common.resolve_rack_id(value, location=rack_location)
                if rack_id:
                    return ("set", field, rack_id)
                logger.warning("Rack '%s' not found, will be omitted", value)
                return ("omit",)
            return ("set", field, value)

        if field == "device_type":
            return await self._resolve_named_id_field(
                field, value, self.common.resolve_device_type_id, "Device type"
            )

        if field == "tags":
            return ("set", field, self.common.normalize_tags(value))

        if field == "ip_namespace":
            return ("namespace", value)

        if field == "custom_fields":
            if isinstance(value, dict):
                return ("set", field, value)
            logger.warning("Invalid custom_fields format: %s, expected dict", type(value))
            return ("omit",)

        return ("set", field, value)

    async def _resolve_named_id_field(
        self,
        field: str,
        value: Any,
        resolver,
        label: str,
    ) -> tuple[str, ...]:
        if not self.common._is_valid_uuid(value):
            resolved_id = await resolver(value)
            if resolved_id:
                return ("set", field, resolved_id)
            logger.warning("%s '%s' not found, will be omitted", label, value)
            return ("omit",)
        return ("set", field, value)

    async def validate_update_data(
        self,
        device_id: str,
        update_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        rack_location: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Validate update data and resolve resource names to UUIDs."""
        logger.debug("Validating update data for device %s: %s", device_id, update_data)

        validated: dict[str, Any] = {}
        ip_namespace: str | None = None

        for raw_field, raw_value in update_data.items():
            prepared = _prepare_update_field(raw_field, raw_value)
            if prepared is None:
                continue
            field, value = prepared

            outcome = await self._resolve_update_field(
                field, value, rack_location=rack_location
            )
            kind = outcome[0]
            if kind == "set":
                validated[outcome[1]] = outcome[2]
            elif kind == "namespace":
                ip_namespace = outcome[1]

        _enforce_rack_position_face(validated)

        logger.info("Validation complete, %s fields to update", len(validated))
        logger.debug("Validated data: %s", validated)
        return validated, ip_namespace

    async def _resolve_primary_ip4_for_patch(
        self,
        *,
        device_id: str,
        primary_ip4: str,
        interface_config: dict[str, Any],
        ip_namespace: str,
        device_name: str | None,
        current_primary_ip4: str | None,
    ) -> str:
        logger.info("Processing primary_ip4 update: %s", primary_ip4)

        create_new = interface_config.get("mgmt_interface_create_on_ip_change", False)
        logger.info("Create new interface on IP change: %s", create_new)

        add_prefixes_automatically = interface_config.get("add_prefixes_automatically", False)
        logger.info("Add prefixes automatically: %s", add_prefixes_automatically)

        use_assigned_ip_if_exists = interface_config.get("use_assigned_ip_if_exists", False)
        logger.info("Use assigned IP if exists: %s", use_assigned_ip_if_exists)

        if create_new:
            logger.info("Creating new interface with new IP address")
            ip_id = await self.common.ensure_interface_with_ip(
                device_id=device_id,
                ip_address=primary_ip4,
                interface_name=interface_config.get("name", "Loopback"),
                interface_type=interface_config.get("type", "virtual"),
                interface_status=interface_config.get("status", "active"),
                ip_namespace=ip_namespace,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )
        else:
            logger.info("Updating existing interface's IP address")
            ip_id = await self.common.update_interface_ip(
                device_id=device_id,
                device_name=device_name,
                old_ip=current_primary_ip4,
                new_ip=primary_ip4,
                namespace=ip_namespace,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )

        logger.info("Updated primary_ip4 to use IP UUID: %s", ip_id)
        return ip_id

    async def _update_device_properties(
        self,
        device_id: str,
        validated_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        ip_namespace: str | None = None,
        device_name: str | None = None,
        current_primary_ip4: str | None = None,
    ) -> list[str]:
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

        update_payload = validated_data.copy()
        updated_fields = list(update_payload.keys())

        if "primary_ip4" in update_payload:
            update_payload["primary_ip4"] = await self._resolve_primary_ip4_for_patch(
                device_id=device_id,
                primary_ip4=update_payload["primary_ip4"],
                interface_config=interface_config or _default_primary_ip_interface_config(),
                ip_namespace=ip_namespace or "Global",
                device_name=device_name,
                current_primary_ip4=current_primary_ip4,
            )

        result = await self.nautobot.rest_request(
            endpoint=f"dcim/devices/{device_id}/",
            method="PATCH",
            data=update_payload,
        )
        if "primary_ip4" in update_payload:
            _verify_primary_ip4_applied(
                device_id=device_id,
                expected_ip_id=update_payload["primary_ip4"],
                result=result,
            )

        logger.info("Successfully updated device %s", device_id)
        return updated_fields
