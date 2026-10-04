"""IP-address operations of the interface workflow."""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.devices.interface_workflow.base import InterfaceOpsBase
from services.nautobot.devices.interface_workflow.payload import (
    ip_map_key,
    normalize_interface_ip_list,
)
from services.nautobot.devices.interface_workflow.state import InterfaceUpdateState

logger = logging.getLogger(__name__)


class InterfaceIpOps(InterfaceOpsBase):
    async def _assign_ips_for_interface(
        self,
        *,
        interface: dict[str, Any],
        interface_id: str,
        state: InterfaceUpdateState,
    ) -> None:
        ip_addresses = interface.get("ip_addresses", [])
        if not ip_addresses and interface.get("ip_address"):
            ip_addresses = [
                {
                    "address": interface["ip_address"],
                    "is_primary": interface.get("is_primary_ipv4", False),
                }
            ]

        logger.info("Found %s IP(s) to assign", len(ip_addresses))

        for idx, ip_data in enumerate(ip_addresses):
            ip_address = ip_data.get("address")
            if not ip_address:
                continue

            logger.info("\n  >> Assigning IP #%s: %s", idx + 1, ip_address)

            temp_interface = interface.copy()
            temp_interface["ip_address"] = ip_address

            ip_assigned = await self._assign_ip_to_interface(
                interface=temp_interface,
                interface_id=interface_id,
                ip_address_map=state.ip_address_map,
                warnings=state.warnings,
            )
            logger.info("  IP assignment result: %s", ip_assigned)

            if ip_assigned and ":" not in ip_address:
                if ip_data.get("is_primary"):
                    state.primary_ipv4_id = ip_assigned
                    logger.info(
                        "  ✓ Interface %s IP %s marked as primary IPv4 (explicit)",
                        interface["name"],
                        ip_address,
                    )
                elif state.primary_ipv4_id is None:
                    state.primary_ipv4_id = ip_assigned
                    logger.info(
                        "  ✓ Interface %s IP %s set as primary IPv4 (first IPv4 found)",
                        interface["name"],
                        ip_address,
                    )

    async def _delete_orphan_device_interfaces(
        self,
        device_id: str,
        desired_names: set[str],
        warnings: list[str],
    ) -> int:
        """Delete device interfaces whose names are not in desired_names."""
        deleted = 0
        endpoint = f"dcim/interfaces/?device_id={device_id}&limit=1000"
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
                    endpoint=f"dcim/interfaces/{interface_id}/",
                    method="DELETE",
                )
                deleted += 1
                logger.info("Deleted orphan device interface %s", name)
            except Exception as exc:
                warnings.append(f"Failed to delete interface {name}: {exc}")

        return deleted

    async def _ensure_one_interface_ip(
        self,
        *,
        interface: dict[str, Any],
        ip_data: dict[str, Any],
        warnings: list[str],
        add_prefixes_automatically: bool,
    ) -> tuple[str, str] | None:
        ip_address = ip_data.get("address")
        if not ip_address:
            logger.warning("  IP data missing 'address' field, skipping")
            return None

        namespace = ip_data.get("namespace") or interface.get("namespace", "Global")
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
                f"Interface {interface['name']}: namespace required for IP "
                f"{ip_address}, skipping IP creation"
            )
            return None

        try:
            namespace_id = await self.common.resolve_namespace_id(namespace)

            ip_kwargs: dict[str, Any] = {}
            if ip_role and ip_role != "none":
                # IP address "role" is a foreign key to Nautobot's generic Role
                # model (extras.Role), not a plain string choice — a raw string
                # here fails Nautobot's validation with an error that doesn't
                # match either special case below, silently dropping the IP.
                role_id = await self.common.resolve_role_id_for_content_type(
                    ip_role, "ipam.ipaddress"
                )
                if role_id:
                    ip_kwargs["role"] = role_id
                    logger.info("  Adding role '%s' (%s) to IP creation", ip_role, role_id)
                else:
                    warnings.append(
                        f"Interface {interface['name']}: IP role '{ip_role}' not found in "
                        "Nautobot for ipam.ipaddress — creating the IP without a role"
                    )
                    logger.warning(
                        "  Role '%s' not found for ipam.ipaddress — omitting role", ip_role
                    )

            logger.info("  Calling ensure_ip_address_exists for %s", ip_address)
            ip_id = await self.common.ensure_ip_address_exists(
                ip_address=ip_address,
                namespace_id=namespace_id,
                status_name=status,
                add_prefixes_automatically=add_prefixes_automatically,
                **ip_kwargs,
            )

            map_key = ip_map_key(interface["name"], ip_address)
            logger.info("  ✓ SUCCESS: IP address %s ready", ip_address)
            logger.info("    - IP ID: %s", ip_id)
            logger.info("    - Map key: %s", map_key)
            return map_key, ip_id

        except Exception as e:
            logger.error("  ✗ Error ensuring IP %s: %s", ip_address, str(e))
            warnings.append(
                f"Interface {interface['name']}: Failed to ensure IP address {ip_address}: {str(e)}"
            )
            if "No suitable parent prefix" in str(e) and not add_prefixes_automatically:
                raise
            return None

    async def _create_ip_addresses(
        self,
        interfaces: list[dict[str, Any]],
        warnings: list[str],
        add_prefixes_automatically: bool = False,
    ) -> dict[str, str]:
        """
        Create IP addresses for all interfaces that need them.

        Uses common.ensure_ip_address_exists() to handle IP creation with proper
        error checking for missing prefixes.

        Args:
            interfaces: List of interface specifications
            warnings: List to append warnings to
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails
                (default: False)

        Returns:
            Dictionary mapping "interface_name:ip_address" to IP UUID
        """
        logger.info("=" * 80)
        logger.info("==== STEP 1: CREATE IP ADDRESSES ====")
        logger.info("=" * 80)
        ip_address_map: dict[str, str] = {}

        for interface in interfaces:
            logger.info("\n--- Processing interface: %s ---", interface["name"])
            logger.info("Interface data: %s", interface)
            ip_addresses = normalize_interface_ip_list(interface)
            if not ip_addresses:
                logger.info(
                    "No ip_address or ip_addresses field found for interface %s, skipping",
                    interface["name"],
                )
                continue

            logger.info("Found %s IP address(es) to process", len(ip_addresses))
            for idx, ip_data in enumerate(ip_addresses):
                logger.info("\n  >> Processing IP #%s: %s", idx + 1, ip_data)
                entry = await self._ensure_one_interface_ip(
                    interface=interface,
                    ip_data=ip_data,
                    warnings=warnings,
                    add_prefixes_automatically=add_prefixes_automatically,
                )
                if entry is not None:
                    key, ip_id = entry
                    ip_address_map[key] = ip_id

        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 1 COMPLETE: IP ADDRESS MAP ====")
        logger.info("Total IPs created/found: %s", len(ip_address_map))
        logger.info("IP address map: %s", ip_address_map)
        logger.info("=" * 80 + "\n")
        return ip_address_map

    async def _clean_interface_ips(
        self,
        interface_id: str,
        interface_name: str,
        warnings: list[str],
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
                f"ipam/ip-address-to-interface/?interface={interface_id}&format=json"
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
                            endpoint=f"ipam/ip-address-to-interface/{assignment_id}/",
                            method="DELETE",
                        )
                        logger.info(
                            "Unassigned IP assignment %s from interface %s",
                            assignment_id,
                            interface_name,
                        )
                    except Exception as delete_error:
                        warnings.append(
                            f"Interface {interface_name}: Failed to unassign existing IP: "
                            f"{str(delete_error)}"
                        )

        except Exception as e:
            warnings.append(
                f"Interface {interface_name}: Failed to check existing IP assignments: {str(e)}"
            )

    async def _assign_ip_to_interface(
        self,
        interface: dict[str, Any],
        interface_id: str,
        ip_address_map: dict[str, str],
        warnings: list[str],
    ) -> str | None:
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
                f"ipam/ip-address-to-interface/?ip_address={ip_id}"
                f"&interface={interface_id}&format=json"
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
            warnings.append(f"Interface {interface['name']}: Failed to assign IP address: {str(e)}")
            return None
