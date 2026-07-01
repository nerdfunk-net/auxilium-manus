"""
Device operations manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot import NautobotService

    from ..resolvers.device_resolver import DeviceResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manager for device-specific operations."""

    def __init__(
        self,
        nautobot_service: NautobotService,
        device_resolver: DeviceResolver,
        network_resolver: NetworkResolver,
    ):
        """
        Initialize the device manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            device_resolver: DeviceResolver instance for device resolution
            network_resolver: NetworkResolver instance for network resolution
        """
        self.nautobot = nautobot_service
        self.device_resolver = device_resolver
        self.network_resolver = network_resolver

    async def get_device_details(
        self, device_id: str, depth: int = 0
    ) -> Dict[str, Any]:
        """
        Fetch device details from Nautobot.

        Args:
            device_id: Device UUID
            depth: API depth parameter (0 for UUIDs only, 1+ for nested objects)

        Returns:
            Device details dictionary

        Raises:
            Exception: If device fetch fails
        """
        logger.info("Fetching device details for %s (depth=%s)", device_id, depth)

        endpoint = f"dcim/devices/{device_id}/"
        if depth > 0:
            endpoint += f"?depth={depth}"

        device_data = await self.nautobot.rest_request(endpoint=endpoint, method="GET")

        logger.debug("Retrieved device data: %s", device_data.get("name", device_id))
        return device_data

    async def extract_primary_ip_address(
        self, device_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract primary IPv4 address from device data.

        Handles both dict format (with 'address' field) and UUID string format
        (by fetching the IP address details).

        Args:
            device_data: Device data dictionary (typically from REST API)

        Returns:
            Primary IPv4 address in CIDR notation (e.g., "10.0.0.1/24") or None

        Note:
            - If primary_ip4 is a dict, extracts the 'address' field
            - If primary_ip4 is a UUID string, fetches IP details from Nautobot
            - Returns None if no primary IP is set
        """
        primary_ip4_field = device_data.get("primary_ip4")
        logger.debug("Device primary_ip4 field: %s", primary_ip4_field)
        logger.debug("Type: %s", type(primary_ip4_field))

        if not primary_ip4_field:
            logger.info("Device has no primary_ip4 set")
            return None

        # Case 1: primary_ip4 is a dict with 'address' field (depth=1+ API response)
        if isinstance(primary_ip4_field, dict):
            current_primary_ip4 = primary_ip4_field.get("address")
            logger.info("Current primary_ip4 (from dict): %s", current_primary_ip4)
            return current_primary_ip4

        # Case 2: primary_ip4 is a UUID string (depth=0 API response)
        elif isinstance(primary_ip4_field, str):
            logger.info("Primary IP field is a UUID: %s", primary_ip4_field)
            try:
                ip_details = await self.nautobot.rest_request(
                    endpoint=f"ipam/ip-addresses/{primary_ip4_field}/",
                    method="GET",
                )
                current_primary_ip4 = ip_details.get("address")
                logger.info(
                    "Current primary_ip4 (from UUID lookup): %s", current_primary_ip4
                )
                return current_primary_ip4
            except NautobotAPIError as e:
                logger.warning("Could not fetch IP details: %s", e)
                return None

        else:
            logger.warning("Unexpected primary_ip4 type: %s", type(primary_ip4_field))
            return None

    async def assign_primary_ip_to_device(
        self, device_id: str, ip_address_id: str
    ) -> bool:
        """
        Assign primary IPv4 address to a device.

        Args:
            device_id: Device UUID
            ip_address_id: IP address UUID to set as primary

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(
                "Assigning primary IPv4 %s to device %s", ip_address_id, device_id
            )

            endpoint = f"dcim/devices/{device_id}/"
            await self.nautobot.rest_request(
                endpoint=endpoint,
                method="PATCH",
                data={"primary_ip4": ip_address_id},
            )

            logger.info("Successfully assigned primary IPv4 to device %s", device_id)
            return True

        except NautobotAPIError as e:
            logger.error(
                "Failed to assign primary IPv4 to device %s: %s", device_id, str(e)
            )
            return False

    async def verify_device_updates(
        self,
        device_id: str,
        expected_updates: Dict[str, Any],
        actual_device: Dict[str, Any],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Verify that device updates were applied successfully.

        Compares expected update values against actual device state.
        Handles special cases:
        - custom_fields: Compares each field individually
        - tags: Skipped (different structure)
        - nested objects: Extracts 'id' field for comparison

        Args:
            device_id: Device UUID
            expected_updates: The data we sent in PATCH/POST
            actual_device: The device object after update

        Returns:
            Tuple of (success: bool, mismatches: List[Dict])
            - success: True if all updates verified, False if any mismatches
            - mismatches: List of mismatch details
        """
        logger.debug("Verifying updates for device %s", device_id)

        mismatches = []

        for field, expected_value in expected_updates.items():
            actual_value = actual_device.get(field)

            # Handle custom_fields specially - compare each field individually
            if field == "custom_fields":
                if isinstance(expected_value, dict) and isinstance(actual_value, dict):
                    for cf_name, cf_expected in expected_value.items():
                        cf_actual = actual_value.get(cf_name)
                        if cf_actual != cf_expected:
                            mismatches.append(
                                {
                                    "field": f"custom_fields.{cf_name}",
                                    "expected": cf_expected,
                                    "actual": cf_actual,
                                }
                            )
                            logger.warning(
                                "Custom field '%s' mismatch: expected '%s', got '%s'",
                                cf_name,
                                cf_expected,
                                cf_actual,
                            )
                continue

            # Skip tags (different structure - tags are objects, not simple strings)
            if field == "tags":
                continue

            # Handle nested objects (e.g., primary_ip4 is an object with 'id')
            if isinstance(actual_value, dict) and "id" in actual_value:
                actual_value = actual_value["id"]

            # Handle choice/enum fields (e.g., face returns {'value': 'front', 'label': 'Front'})
            elif isinstance(actual_value, dict) and "value" in actual_value:
                actual_value = actual_value["value"]

            # Normalize types for scalar comparison (e.g., int 10 vs str '10')
            if actual_value != expected_value:
                if str(actual_value) == str(expected_value):
                    continue

                mismatches.append(
                    {
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
                logger.warning(
                    "Field '%s' mismatch: expected '%s', got '%s'",
                    field,
                    expected_value,
                    actual_value,
                )

        if mismatches:
            logger.warning("Verification found %s mismatch(es)", len(mismatches))
            return False, mismatches
        else:
            logger.debug("All updates verified successfully")
            return True, []
