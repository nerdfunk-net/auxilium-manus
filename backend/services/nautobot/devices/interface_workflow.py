"""
Interface Management Workflow Service for Nautobot Devices.

This service handles the high-level orchestration of creating, updating, and managing
interfaces and their IP addresses for devices in Nautobot. It is designed to be used
by DeviceUpdateService and other services that need to manipulate device interfaces.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from services.nautobot import NautobotService
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.types import InterfaceUpdateResult

logger = logging.getLogger(__name__)


class InterfaceManagerService:
    """
    Service for managing device interfaces and IP addresses in Nautobot.

    Handles the complete workflow:
    1. Creating IP addresses in IPAM
    2. Creating or updating interfaces
    3. Assigning IP addresses to interfaces
    4. Setting primary IPv4 addresses
    5. Cleaning up old IP assignments
    """

    def __init__(self, nautobot_service: NautobotService):
        """
        Initialize the interface manager service.

        Args:
            nautobot_service: NautobotService instance for API calls
        """
        self.nautobot = nautobot_service
        self.common = DeviceCommonService(nautobot_service)

    async def update_device_interfaces(
        self,
        device_id: str,
        interfaces: List[Dict[str, Any]],
        add_prefixes_automatically: bool = False,
        sync_interfaces: bool = False,
    ) -> InterfaceUpdateResult:
        """
        Create or update multiple interfaces for a device.

        This method handles:
        1. Creating IP addresses in IPAM
        2. Creating interfaces on the device
        3. Assigning IP addresses to interfaces
        4. Setting primary IPv4 if specified

        Args:
            device_id: Device UUID
            interfaces: List of interface dicts (can be InterfaceSpec or plain dicts)
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails (default: False)

        Returns:
            InterfaceUpdateResult with operation statistics and warnings
        """
        logger.info(
            "Creating/updating %s interface(s) for device %s",
            len(interfaces),
            device_id,
        )

        created_interfaces: List[str] = []
        updated_interfaces: List[str] = []
        failed_interfaces: List[str] = []
        ip_address_map = {}
        primary_ipv4_id = None
        warnings = []
        cleaned_interfaces: Set[str] = set()
        interfaces_deleted = 0

        desired_names = {
            (iface.get("name") or "").strip()
            for iface in interfaces
            if (iface.get("name") or "").strip()
        }

        if sync_interfaces:
            interfaces_deleted = await self._delete_orphan_device_interfaces(
                device_id=device_id,
                desired_names=desired_names,
                warnings=warnings,
            )

        # Step 1: Create IP addresses first
        ip_address_map = await self._create_ip_addresses(
            interfaces=interfaces,
            warnings=warnings,
            add_prefixes_automatically=add_prefixes_automatically,
        )

        # Step 2: Create or update interfaces
        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 2: CREATE OR UPDATE INTERFACES ====")
        logger.info("=" * 80)
        for interface in interfaces:
            try:
                logger.info("\n--- Processing interface: %s ---", interface["name"])
                interface_id, was_updated = await self._create_or_update_interface(
                    device_id=device_id,
                    interface=interface,
                    warnings=warnings,
                )
                logger.info("Interface ID returned: %s", interface_id)

                if interface_id:
                    iface_name = interface["name"]
                    if was_updated:
                        if iface_name not in updated_interfaces:
                            updated_interfaces.append(iface_name)
                    elif iface_name not in created_interfaces:
                        created_interfaces.append(iface_name)

                    # Clean existing IP assignments (once per interface)
                    if interface_id not in cleaned_interfaces:
                        logger.info(
                            "Cleaning existing IPs from interface %s", interface["name"]
                        )
                        await self._clean_interface_ips(
                            interface_id=interface_id,
                            interface_name=interface["name"],
                            warnings=warnings,
                        )
                        cleaned_interfaces.add(interface_id)
                    else:
                        logger.info("Interface %s already cleaned", interface["name"])

                    # Assign IP addresses - handle both array and single formats
                    logger.info(
                        "\n==== STEP 3: ASSIGN IP(S) TO INTERFACE %s ====",
                        interface["name"],
                    )
                    logger.info("Interface ID: %s", interface_id)

                    # Get IP addresses in array format
                    ip_addresses = interface.get("ip_addresses", [])
                    if not ip_addresses and interface.get("ip_address"):
                        # Backwards compatibility: single ip_address
                        ip_addresses = [
                            {
                                "address": interface["ip_address"],
                                "is_primary": interface.get("is_primary_ipv4", False),
                            }
                        ]

                    logger.info("Found %s IP(s) to assign", len(ip_addresses))

                    # Assign each IP address
                    for idx, ip_data in enumerate(ip_addresses):
                        ip_address = ip_data.get("address")
                        if not ip_address:
                            continue

                        logger.info("\n  >> Assigning IP #%s: %s", idx + 1, ip_address)

                        # Create a temporary interface dict for the assignment call
                        temp_interface = interface.copy()
                        temp_interface["ip_address"] = ip_address

                        ip_assigned = await self._assign_ip_to_interface(
                            interface=temp_interface,
                            interface_id=interface_id,
                            ip_address_map=ip_address_map,
                            warnings=warnings,
                        )
                        logger.info("  IP assignment result: %s", ip_assigned)

                        # Track if this should be primary IPv4
                        if ip_assigned:
                            is_ipv4 = ip_address and ":" not in ip_address
                            if is_ipv4:
                                # Check if this IP is marked as primary
                                if ip_data.get("is_primary"):
                                    primary_ipv4_id = ip_assigned
                                    logger.info(
                                        "  ✓ Interface %s IP %s marked as primary IPv4 (explicit)",
                                        interface["name"],
                                        ip_address,
                                    )
                                elif primary_ipv4_id is None:
                                    primary_ipv4_id = ip_assigned
                                    logger.info(
                                        "  ✓ Interface %s IP %s set as primary IPv4 (first IPv4 found)",
                                        interface["name"],
                                        ip_address,
                                    )

            except Exception as e:
                error_msg = str(e)
                failed_interfaces.append(interface["name"])
                warnings.append(
                    f"Interface {interface['name']}: Failed to process interface: {error_msg}"
                )
                logger.error(
                    "Error processing interface %s: %s", interface["name"], error_msg
                )

        # Step 3: Set primary IPv4 if found
        if primary_ipv4_id:
            await self._set_primary_ipv4(
                device_id=device_id,
                primary_ipv4_id=primary_ipv4_id,
                warnings=warnings,
            )

        return InterfaceUpdateResult(
            interfaces_created=len(created_interfaces),
            interfaces_updated=len(updated_interfaces),
            interfaces_failed=len(failed_interfaces),
            interfaces_deleted=interfaces_deleted,
            ip_addresses_created=len(ip_address_map),
            primary_ip4_id=primary_ipv4_id,
            warnings=warnings,
        )

    async def _delete_orphan_device_interfaces(
        self,
        device_id: str,
        desired_names: Set[str],
        warnings: List[str],
    ) -> int:
        """Delete device interfaces whose names are not in desired_names."""
        deleted = 0
        endpoint = "dcim/interfaces/?device_id=%s&limit=1000" % device_id
        try:
            response = await self.nautobot.rest_request(endpoint=endpoint, method="GET")
        except Exception as exc:
            warnings.append(f"Failed to list device interfaces for sync: {exc}")
            return 0

        for existing in response.get("results", []) if response else []:
            name = (existing.get("name") or "").strip()
            interface_id = existing.get("id")
            if not name or not interface_id or name in desired_names:
                continue
            try:
                await self._clean_interface_ips(
                    interface_id=interface_id,
                    interface_name=name,
                    warnings=warnings,
                )
                await self.nautobot.rest_request(
                    endpoint="dcim/interfaces/%s/" % interface_id,
                    method="DELETE",
                )
                deleted += 1
                logger.info("Deleted orphan device interface %s", name)
            except Exception as exc:
                warnings.append(f"Failed to delete interface {name}: {exc}")

        return deleted

    async def _create_ip_addresses(
        self,
        interfaces: List[Dict[str, Any]],
        warnings: List[str],
        add_prefixes_automatically: bool = False,
    ) -> Dict[str, str]:
        """
        Create IP addresses for all interfaces that need them.

        Uses common.ensure_ip_address_exists() to handle IP creation with proper
        error checking for missing prefixes.

        Args:
            interfaces: List of interface specifications
            warnings: List to append warnings to
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails (default: False)

        Returns:
            Dictionary mapping "interface_name:ip_address" to IP UUID
        """
        logger.info("=" * 80)
        logger.info("==== STEP 1: CREATE IP ADDRESSES ====")
        logger.info("=" * 80)
        ip_address_map = {}

        for interface in interfaces:
            logger.info("\n--- Processing interface: %s ---", interface["name"])
            logger.info("Interface data: %s", interface)

            # Handle both formats: ip_addresses (array) and ip_address (string)
            ip_addresses = interface.get("ip_addresses", [])
            if not ip_addresses and interface.get("ip_address"):
                # Backwards compatibility: convert single ip_address to array format
                logger.info("Found single ip_address field, converting to array format")
                ip_addresses = [
                    {
                        "address": interface["ip_address"],
                        "namespace": interface.get("namespace", "Global"),
                        "ip_role": interface.get("ip_role"),
                    }
                ]

            if not ip_addresses:
                logger.info(
                    "No ip_address or ip_addresses field found for interface %s, skipping",
                    interface["name"],
                )
                continue

            logger.info("Found %s IP address(es) to process", len(ip_addresses))

            # Process each IP address for this interface
            for idx, ip_data in enumerate(ip_addresses):
                logger.info("\n  >> Processing IP #%s: %s", idx + 1, ip_data)

                ip_address = ip_data.get("address")
                if not ip_address:
                    logger.warning("  IP data missing 'address' field, skipping")
                    continue

                # Get namespace from IP data or fall back to interface level
                namespace = ip_data.get("namespace") or interface.get(
                    "namespace", "Global"
                )
                status = interface.get("status", "active")
                ip_role = ip_data.get("ip_role")

                logger.info(
                    "  Extracted values: ip=%s, namespace=%s, status=%s, ip_role=%s",
                    ip_address,
                    namespace,
                    status,
                    ip_role,
                )

                if not namespace:
                    warnings.append(
                        f"Interface {interface['name']}: namespace required for IP {ip_address}, skipping IP creation"
                    )
                    continue

                try:
                    # Resolve namespace to UUID
                    namespace_id = await self.common.resolve_namespace_id(namespace)

                    # Build kwargs for additional IP fields
                    ip_kwargs = {}
                    if ip_role and ip_role != "none":
                        ip_kwargs["role"] = ip_role
                        logger.info("  Adding role '%s' to IP creation", ip_role)

                    # Use common service to ensure IP exists (handles all error cases)
                    logger.info("  Calling ensure_ip_address_exists for %s", ip_address)
                    ip_id = await self.common.ensure_ip_address_exists(
                        ip_address=ip_address,
                        namespace_id=namespace_id,
                        status_name=status,
                        add_prefixes_automatically=add_prefixes_automatically,
                        **ip_kwargs,
                    )

                    map_key = f"{interface['name']}:{ip_address}"
                    ip_address_map[map_key] = ip_id
                    logger.info("  ✓ SUCCESS: IP address %s ready", ip_address)
                    logger.info("    - IP ID: %s", ip_id)
                    logger.info("    - Map key: %s", map_key)

                except Exception as e:
                    logger.error("  ✗ Error ensuring IP %s: %s", ip_address, str(e))
                    warnings.append(
                        f"Interface {interface['name']}: Failed to ensure IP address {ip_address}: {str(e)}"
                    )
                    # If this is a missing prefix error and add_prefixes_automatically is False,
                    # the exception should propagate to stop the device creation
                    if (
                        "No suitable parent prefix" in str(e)
                        and not add_prefixes_automatically
                    ):
                        raise

        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 1 COMPLETE: IP ADDRESS MAP ====")
        logger.info("Total IPs created/found: %s", len(ip_address_map))
        logger.info("IP address map: %s", ip_address_map)
        logger.info("=" * 80 + "\n")
        return ip_address_map

    async def _create_or_update_interface(
        self,
        device_id: str,
        interface: Dict[str, Any],
        warnings: List[str],
    ) -> tuple[Optional[str], bool]:
        """
        Create or update a single interface.

        Args:
            device_id: Device UUID
            interface: Interface specification
            warnings: List to append warnings to

        Returns:
            Tuple of (interface UUID if successful, was_updated flag)
        """
        # Validate required fields before hitting Nautobot
        # Nautobot interface type slugs are always lowercase (e.g. "virtual", "1000base-t")
        # Frontend may store the display name (e.g. "Virtual") — normalize to lowercase slug
        interface_type = (interface.get("type") or "").strip().lower()
        if not interface_type:
            warnings.append(
                f"Interface {interface['name']}: 'type' is required but was not provided — skipping"
            )
            logger.warning(
                "Interface '%s' has no type set, skipping creation", interface["name"]
            )
            return None, False

        # Resolve status to UUID — use "or" fallback so empty string also defaults to "active"
        interface_status = interface.get("status") or "active"
        interface_status_id = await self.common.resolve_status_id(
            interface_status, "dcim.interface"
        )

        interface_payload: Dict[str, Any] = {
            "name": interface["name"],
            "device": device_id,
            "type": interface_type,
            "status": interface_status_id,
        }

        optional_fields = [
            "enabled",
            "mgmt_only",
            "description",
            "mac_address",
            "mtu",
            "mode",
        ]
        for field in optional_fields:
            if field in interface and interface[field] is not None:
                # "none" is the UI sentinel for "no mode"; Nautobot rejects it
                if field == "mode" and interface[field] == "none":
                    continue
                interface_payload[field] = interface[field]

        # Nautobot REST API requires VLAN references as {"id": uuid}
        untagged_vlan = interface.get("untagged_vlan")
        if untagged_vlan and untagged_vlan != "none":
            interface_payload["untagged_vlan"] = {"id": untagged_vlan}

        tagged_vlans = interface.get("tagged_vlans")
        if tagged_vlans:
            interface_payload["tagged_vlans"] = [{"id": vid} for vid in tagged_vlans]

        existing_id = await self.common.resolve_interface_by_name(
            device_id=device_id,
            interface_name=interface["name"],
        )
        if existing_id:
            patch_payload = {
                k: v
                for k, v in interface_payload.items()
                if k not in ("name", "device")
            }
            try:
                await self.nautobot.rest_request(
                    endpoint="dcim/interfaces/%s/" % existing_id,
                    method="PATCH",
                    data=patch_payload,
                )
                logger.info(
                    "Updated interface %s with ID: %s", interface["name"], existing_id
                )
                return existing_id, True
            except Exception as patch_error:
                warnings.append(
                    f"Interface {interface['name']}: Failed to update: {patch_error}"
                )
                return existing_id, True

        logger.debug("Creating interface with payload: %s", interface_payload)

        try:
            interface_response = await self.nautobot.rest_request(
                endpoint="dcim/interfaces/",
                method="POST",
                data=interface_payload,
            )

            if interface_response and "id" in interface_response:
                interface_id = interface_response["id"]
                logger.info(
                    "Created interface %s with ID: %s", interface["name"], interface_id
                )
                return interface_id, False

        except Exception as create_error:
            if "must make a unique set" in str(create_error).lower():
                interface_id = await self.common.resolve_interface_by_name(
                    device_id=device_id,
                    interface_name=interface["name"],
                )
                if interface_id:
                    patch_payload = {
                        k: v
                        for k, v in interface_payload.items()
                        if k not in ("name", "device")
                    }
                    try:
                        await self.nautobot.rest_request(
                            endpoint="dcim/interfaces/%s/" % interface_id,
                            method="PATCH",
                            data=patch_payload,
                        )
                    except Exception as patch_error:
                        warnings.append(
                            f"Interface {interface['name']}: Failed to patch: {patch_error}"
                        )
                    return interface_id, True
                warnings.append(
                    f"Interface {interface['name']}: Interface exists but could not be found"
                )
            else:
                logger.error(
                    "Failed to create interface '%s': %s",
                    interface["name"],
                    str(create_error),
                )
                warnings.append(
                    f"Interface {interface['name']}: Failed to create interface: {str(create_error)}"
                )

        return None, False

    async def _clean_interface_ips(
        self,
        interface_id: str,
        interface_name: str,
        warnings: List[str],
    ) -> None:
        """
        Remove all existing IP assignments from an interface.

        Args:
            interface_id: Interface UUID
            interface_name: Interface name (for logging)
            warnings: List to append warnings to
        """
        try:
            existing_assignments_endpoint = (
                "ipam/ip-address-to-interface/?interface=%s&format=json" % interface_id
            )
            existing_assignments = await self.nautobot.rest_request(
                endpoint=existing_assignments_endpoint, method="GET"
            )

            if existing_assignments and existing_assignments.get("count", 0) > 0:
                logger.info(
                    "Found %s existing IP assignment(s) on interface %s, removing them...",
                    existing_assignments["count"],
                    interface_name,
                )
                for assignment in existing_assignments.get("results", []):
                    assignment_id = assignment["id"]
                    try:
                        await self.nautobot.rest_request(
                            endpoint="ipam/ip-address-to-interface/%s/" % assignment_id,
                            method="DELETE",
                        )
                        logger.info(
                            "Unassigned IP assignment %s from interface %s",
                            assignment_id,
                            interface_name,
                        )
                    except Exception as delete_error:
                        warnings.append(
                            f"Interface {interface_name}: Failed to unassign existing IP: {str(delete_error)}"
                        )

        except Exception as e:
            warnings.append(
                f"Interface {interface_name}: Failed to check existing IP assignments: {str(e)}"
            )

    async def _assign_ip_to_interface(
        self,
        interface: Dict[str, Any],
        interface_id: str,
        ip_address_map: Dict[str, str],
        warnings: List[str],
    ) -> Optional[str]:
        """
        Assign an IP address to an interface.

        Args:
            interface: Interface specification
            interface_id: Interface UUID
            ip_address_map: Map of interface:ip to IP UUIDs
            warnings: List to append warnings to

        Returns:
            IP UUID if successfully assigned, None otherwise
        """
        logger.info("_assign_ip_to_interface called")
        logger.info("  Interface: %s", interface["name"])
        logger.info("  Interface ID: %s", interface_id)
        logger.info("  IP address map keys: %s", list(ip_address_map.keys()))

        ip_address = interface.get("ip_address")
        if not ip_address:
            logger.warning("No ip_address field in interface data")
            return None

        map_key = f"{interface['name']}:{ip_address}"
        logger.info("Looking for map_key: '%s'", map_key)

        if map_key not in ip_address_map:
            logger.error("✗ IP address not found in map for key '%s'", map_key)
            logger.error("Available keys: %s", list(ip_address_map.keys()))
            return None

        ip_id = ip_address_map[map_key]
        logger.info("✓ Found IP in map: %s (ID: %s)", ip_address, ip_id)
        logger.info("Attempting to assign IP to interface %s", interface["name"])

        try:
            # Check if assignment already exists
            check_assignment_endpoint = (
                "ipam/ip-address-to-interface/?ip_address=%s&interface=%s&format=json"
                % (
                    ip_id,
                    interface_id,
                )
            )
            existing_assignment = await self.nautobot.rest_request(
                endpoint=check_assignment_endpoint, method="GET"
            )

            if existing_assignment and existing_assignment.get("count", 0) > 0:
                logger.info(
                    "✓ IP-to-Interface assignment already exists for IP %s and interface %s",
                    ip_id,
                    interface["name"],
                )
            else:
                # Create new assignment
                assignment_payload = {
                    "ip_address": ip_id,
                    "interface": interface_id,
                }
                logger.info("Creating assignment with payload: %s", assignment_payload)
                result = await self.nautobot.rest_request(
                    endpoint="ipam/ip-address-to-interface/",
                    method="POST",
                    data=assignment_payload,
                )
                logger.info("Assignment response: %s", result)
                logger.info(
                    "✓ Created new IP-to-Interface assignment: IP %s → interface %s",
                    ip_id,
                    interface["name"],
                )

            return ip_id

        except Exception as e:
            logger.error("✗ Exception during IP assignment: %s", str(e))
            logger.error(
                "Interface: %s, IP: %s, Interface ID: %s",
                interface["name"],
                ip_address,
                interface_id,
            )
            warnings.append(
                f"Interface {interface['name']}: Failed to assign IP address: {str(e)}"
            )
            return None

    async def _set_primary_ipv4(
        self,
        device_id: str,
        primary_ipv4_id: str,
        warnings: List[str],
    ) -> None:
        """
        Set the primary IPv4 address for a device.

        Args:
            device_id: Device UUID
            primary_ipv4_id: IP address UUID to set as primary
            warnings: List to append warnings to
        """
        try:
            update_payload = {"primary_ip4": primary_ipv4_id}
            await self.nautobot.rest_request(
                endpoint="dcim/devices/%s/" % device_id,
                method="PATCH",
                data=update_payload,
            )
            logger.info("Set primary IPv4 to %s", primary_ipv4_id)
        except Exception as e:
            warnings.append(f"Failed to set primary IPv4: {str(e)}")
