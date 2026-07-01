"""
Virtual machine manager for Nautobot virtualization operations.

This manager handles lifecycle operations (create/update) for virtual machines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot import NautobotService

logger = logging.getLogger(__name__)


class VirtualMachineManager:
    """Manager for virtual machine lifecycle operations."""

    def __init__(self, nautobot_service: NautobotService):
        """
        Initialize the VM manager.

        Args:
            nautobot_service: NautobotService instance for API calls
        """
        self.nautobot = nautobot_service

    async def assign_ip_to_virtual_interface(
        self, ip_address_id: str, virtual_interface_id: str
    ) -> bool:
        """
        Assign an IP address to a virtual interface.

        Uses the IP-to-Interface mapping endpoint with the vm_interface field.

        Args:
            ip_address_id: IP address UUID
            virtual_interface_id: Virtual interface UUID

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: If assignment fails
        """
        logger.info(
            "Assigning IP %s to virtual interface %s",
            ip_address_id,
            virtual_interface_id,
        )

        # Check if assignment already exists
        check_endpoint = (
            "ipam/ip-address-to-interface/?ip_address=%s&vm_interface=%s"
            % (
                ip_address_id,
                virtual_interface_id,
            )
        )

        existing_assignment = await self.nautobot.rest_request(
            endpoint=check_endpoint,
            method="GET",
        )

        if existing_assignment and existing_assignment.get("count", 0) > 0:
            logger.info("IP-to-virtual-interface assignment already exists, skipping")
            return True

        # Create the IP-to-Interface mapping using vm_interface field
        endpoint = "ipam/ip-address-to-interface/"
        payload = {
            "ip_address": {"id": ip_address_id},
            "vm_interface": {"id": virtual_interface_id},
        }

        try:
            result = await self.nautobot.rest_request(
                endpoint=endpoint,
                method="POST",
                data=payload,
            )

            logger.info(
                "Assigned IP to virtual interface, assignment ID: %s", result.get("id")
            )
            return True

        except NautobotAPIError as e:
            logger.error(
                "Failed to assign IP to virtual interface %s: %s",
                virtual_interface_id,
                str(e),
            )
            raise NautobotAPIError(
                f"Failed to assign IP to virtual interface: {str(e)}"
            )

    async def assign_primary_ip_to_vm(self, vm_id: str, ip_address_id: str) -> bool:
        """
        Assign primary IPv4 address to a virtual machine.

        Args:
            vm_id: Virtual machine UUID
            ip_address_id: IP address UUID to set as primary

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: If assignment fails
        """
        logger.info("Assigning primary IPv4 %s to VM %s", ip_address_id, vm_id)

        endpoint = "virtualization/virtual-machines/%s/" % vm_id
        payload = {"primary_ip4": {"id": ip_address_id}}

        try:
            await self.nautobot.rest_request(
                endpoint=endpoint,
                method="PATCH",
                data=payload,
            )

            logger.info("Successfully set primary IPv4 for VM %s", vm_id)
            return True

        except NautobotAPIError as e:
            logger.error("Failed to assign primary IPv4 to VM %s: %s", vm_id, str(e))
            raise NautobotAPIError(f"Failed to assign primary IP to VM: {str(e)}")

    async def update_virtual_machine(
        self,
        vm_id: str,
        *,
        cluster_id: Optional[str] = None,
        status_id: Optional[str] = None,
        role_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        vcpus: Optional[int] = None,
        memory: Optional[int] = None,
        disk: Optional[int] = None,
        software_version_id: Optional[str] = None,
        software_image_file_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        custom_fields: Optional[dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Update a virtual machine via PATCH."""
        vm_data: Dict[str, Any] = {}

        if status_id:
            vm_data["status"] = {"id": status_id}
        if cluster_id:
            vm_data["cluster"] = {"id": cluster_id}
        if role_id:
            vm_data["role"] = {"id": role_id}
        if platform_id:
            vm_data["platform"] = {"id": platform_id}
        if vcpus is not None:
            vm_data["vcpus"] = vcpus
        if memory is not None:
            vm_data["memory"] = memory
        if disk is not None:
            vm_data["disk"] = disk
        if software_version_id:
            vm_data["software_version"] = {"id": software_version_id}
        if software_image_file_ids is not None:
            vm_data["software_image_files"] = [
                {"id": img_id} for img_id in software_image_file_ids
            ]
        if tags is not None:
            vm_data["tags"] = [{"id": tag_id} for tag_id in tags]
        if custom_fields is not None:
            vm_data["custom_fields"] = custom_fields

        if not vm_data:
            logger.info("No VM fields to update for %s", vm_id)
            return await self.nautobot.rest_request(
                endpoint="virtualization/virtual-machines/%s/" % vm_id,
                method="GET",
            )

        logger.info("Updating virtual machine %s", vm_id)
        try:
            result = await self.nautobot.rest_request(
                endpoint="virtualization/virtual-machines/%s/" % vm_id,
                method="PATCH",
                data=vm_data,
            )
            logger.info("Updated VM %s", vm_id)
            return result
        except NautobotAPIError as e:
            logger.error("Failed to update VM %s: %s", vm_id, e, exc_info=True)
            raise NautobotAPIError(f"Failed to update virtual machine: {str(e)}")

    async def list_virtual_interfaces(self, vm_id: str) -> list[Dict[str, Any]]:
        """List virtual interfaces for a VM."""
        endpoint = "virtualization/interfaces/?virtual_machine_id=%s&limit=1000" % vm_id
        response = await self.nautobot.rest_request(endpoint=endpoint, method="GET")
        if not response:
            return []
        return response.get("results", [])

    async def update_virtual_interface(
        self,
        interface_id: str,
        *,
        status_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        mac_address: Optional[str] = None,
        mtu: Optional[int] = None,
        description: Optional[str] = None,
        mode: Optional[str] = None,
        untagged_vlan_id: Optional[str] = None,
        tagged_vlan_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Update a virtual interface via PATCH."""
        interface_data: Dict[str, Any] = {}

        if status_id:
            interface_data["status"] = {"id": status_id}
        if enabled is not None:
            interface_data["enabled"] = enabled
        if mac_address is not None:
            interface_data["mac_address"] = mac_address
        if mtu is not None:
            interface_data["mtu"] = mtu
        if description is not None:
            interface_data["description"] = description
        if mode is not None and mode != "none":
            interface_data["mode"] = mode
        if untagged_vlan_id:
            interface_data["untagged_vlan"] = {"id": untagged_vlan_id}
        if tagged_vlan_ids is not None:
            interface_data["tagged_vlans"] = [
                {"id": vlan_id} for vlan_id in tagged_vlan_ids
            ]
        if tags is not None:
            interface_data["tags"] = [{"id": tag_id} for tag_id in tags]

        if not interface_data:
            return await self.nautobot.rest_request(
                endpoint="virtualization/interfaces/%s/" % interface_id,
                method="GET",
            )

        try:
            return await self.nautobot.rest_request(
                endpoint="virtualization/interfaces/%s/" % interface_id,
                method="PATCH",
                data=interface_data,
            )
        except NautobotAPIError as e:
            logger.error("Failed to update virtual interface %s: %s", interface_id, e)
            raise NautobotAPIError(f"Failed to update virtual interface: {str(e)}")

    async def clean_virtual_interface_ips(self, interface_id: str) -> None:
        """Remove all IP assignments from a virtual interface."""
        check_endpoint = (
            "ipam/ip-address-to-interface/?vm_interface=%s&limit=1000" % interface_id
        )
        existing = await self.nautobot.rest_request(
            endpoint=check_endpoint, method="GET"
        )
        if not existing or existing.get("count", 0) == 0:
            return

        for assignment in existing.get("results", []):
            assignment_id = assignment.get("id")
            if not assignment_id:
                continue
            await self.nautobot.rest_request(
                endpoint="ipam/ip-address-to-interface/%s/" % assignment_id,
                method="DELETE",
            )

    async def delete_virtual_interface(self, interface_id: str) -> None:
        """Delete a virtual interface."""
        await self.clean_virtual_interface_ips(interface_id)
        await self.nautobot.rest_request(
            endpoint="virtualization/interfaces/%s/" % interface_id,
            method="DELETE",
        )
        logger.info("Deleted virtual interface %s", interface_id)

    async def delete_virtual_machine(self, vm_id: str) -> None:
        """
        Delete a virtual machine from Nautobot.

        Removes all virtual interfaces first, then deletes the VM.
        """
        logger.info("Deleting virtual machine %s", vm_id)

        for interface in await self.list_virtual_interfaces(vm_id):
            interface_id = interface.get("id")
            if interface_id:
                await self.delete_virtual_interface(interface_id)

        await self.nautobot.rest_request(
            endpoint="virtualization/virtual-machines/%s/" % vm_id,
            method="DELETE",
        )
        logger.info("Deleted virtual machine %s", vm_id)

    async def create_virtual_machine(
        self,
        name: str,
        cluster_id: str,
        status_id: str,
        role_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        vcpus: Optional[int] = None,
        memory: Optional[int] = None,
        disk: Optional[int] = None,
        software_version_id: Optional[str] = None,
        software_image_file_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        custom_fields: Optional[dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a virtual machine in Nautobot using the REST API.

        Args:
            name: VM name
            cluster_id: UUID of the cluster
            status_id: UUID of the status
            role_id: Optional UUID of the role
            platform_id: Optional UUID of the platform
            vcpus: Optional number of virtual CPUs
            memory: Optional memory in MB
            disk: Optional disk size in GB
            software_version_id: Optional UUID of software version
            software_image_file_ids: Optional list of software image file UUIDs
            tags: Optional list of tag UUIDs
            custom_fields: Optional dict of custom field key-value pairs

        Returns:
            Dict containing the created VM data with 'id' field

        Raises:
            Exception: If VM creation fails
        """
        logger.info("Creating virtual machine '%s' in cluster %s", name, cluster_id)

        # Build the VM data payload according to Nautobot's REST API schema
        vm_data: Dict[str, Any] = {
            "name": name,
            "cluster": {"id": cluster_id},
            "status": {"id": status_id},
        }

        # Add optional fields only if provided
        if role_id:
            vm_data["role"] = {"id": role_id}

        if platform_id:
            vm_data["platform"] = {"id": platform_id}

        if vcpus is not None:
            vm_data["vcpus"] = vcpus

        if memory is not None:
            vm_data["memory"] = memory

        if disk is not None:
            vm_data["disk"] = disk

        if software_version_id:
            vm_data["software_version"] = {"id": software_version_id}

        if software_image_file_ids:
            vm_data["software_image_files"] = [
                {"id": img_id} for img_id in software_image_file_ids
            ]

        if tags:
            vm_data["tags"] = [{"id": tag_id} for tag_id in tags]

        if custom_fields:
            vm_data["custom_fields"] = custom_fields

        try:
            result = await self.nautobot.rest_request(
                "virtualization/virtual-machines/", method="POST", data=vm_data
            )

            logger.info("Created VM '%s' with ID %s", name, result.get("id"))
            return result

        except NautobotAPIError as e:
            logger.error("Failed to create VM '%s': %s", name, e, exc_info=True)
            raise NautobotAPIError(f"Failed to create virtual machine: {str(e)}")

    async def create_virtual_interface(
        self,
        name: str,
        virtual_machine_id: str,
        status_id: str,
        enabled: bool = True,
        mac_address: Optional[str] = None,
        mtu: Optional[int] = None,
        description: Optional[str] = None,
        mode: Optional[str] = None,
        untagged_vlan_id: Optional[str] = None,
        tagged_vlan_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a virtual interface for a VM in Nautobot using the REST API.

        Args:
            name: Interface name
            virtual_machine_id: UUID of the VM
            status_id: UUID of the interface status
            enabled: Whether the interface is enabled (default: True)
            mac_address: Optional MAC address
            mtu: Optional MTU value
            description: Optional description
            mode: Optional mode ('access', 'tagged', etc.)
            untagged_vlan_id: Optional UUID of untagged VLAN
            tagged_vlan_ids: Optional list of tagged VLAN UUIDs
            tags: Optional list of tag UUIDs

        Returns:
            Dict containing the created interface data with 'id' field

        Raises:
            Exception: If interface creation fails
        """
        logger.info(
            "Creating virtual interface '%s' for VM %s", name, virtual_machine_id
        )

        # Build the interface data payload according to Nautobot's REST API schema
        interface_data: Dict[str, Any] = {
            "name": name,
            "virtual_machine": {"id": virtual_machine_id},
            "status": {"id": status_id},
            "enabled": enabled,
        }

        # Add optional fields only if provided
        if mac_address:
            interface_data["mac_address"] = mac_address

        if mtu is not None:
            interface_data["mtu"] = mtu

        if description:
            interface_data["description"] = description

        if mode and mode != "none":
            interface_data["mode"] = mode

        if untagged_vlan_id:
            interface_data["untagged_vlan"] = {"id": untagged_vlan_id}

        if tagged_vlan_ids:
            interface_data["tagged_vlans"] = [
                {"id": vlan_id} for vlan_id in tagged_vlan_ids
            ]

        if tags:
            interface_data["tags"] = [{"id": tag_id} for tag_id in tags]

        try:
            result = await self.nautobot.rest_request(
                "virtualization/interfaces/", method="POST", data=interface_data
            )

            logger.info(
                "Created virtual interface '%s' with ID %s", name, result.get("id")
            )
            return result

        except NautobotAPIError as e:
            logger.error(
                "Failed to create interface '%s' for VM %s: %s",
                name,
                virtual_machine_id,
                e,
                exc_info=True,
            )
            raise NautobotAPIError(f"Failed to create virtual interface: {str(e)}")
