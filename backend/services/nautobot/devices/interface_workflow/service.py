"""Interface Management Workflow Service for Nautobot Devices.

High-level orchestration of creating, updating and managing interfaces and their IP addresses
for devices in Nautobot. Used by DeviceUpdateService and DeviceCreationService.
"""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.api_protocol import NautobotApi
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.interface_workflow.ip_ops import InterfaceIpOps
from services.nautobot.devices.interface_workflow.record_ops import InterfaceRecordOps
from services.nautobot.devices.interface_workflow.state import InterfaceUpdateState
from services.nautobot.devices.types import InterfaceUpdateResult

logger = logging.getLogger(__name__)


class InterfaceManagerService(InterfaceIpOps, InterfaceRecordOps):
    """
    Service for managing device interfaces and IP addresses in Nautobot.

    Handles the complete workflow:
    1. Creating IP addresses in IPAM
    2. Creating or updating interfaces
    3. Assigning IP addresses to interfaces
    4. Setting primary IPv4 addresses
    5. Cleaning up old IP assignments
    """

    def __init__(self, nautobot_service: NautobotApi):
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
        interfaces: list[dict[str, Any]],
        add_prefixes_automatically: bool = False,
        sync_interfaces: bool = False,
        device_location_id: str | None = None,
    ) -> InterfaceUpdateResult:
        """Create or update interfaces: IPs → interfaces → assign → optional primary."""
        logger.info(
            "Creating/updating %s interface(s) for device %s",
            len(interfaces),
            device_id,
        )

        state = InterfaceUpdateState()
        desired_names = {
            (iface.get("name") or "").strip()
            for iface in interfaces
            if (iface.get("name") or "").strip()
        }

        if sync_interfaces:
            state.interfaces_deleted = await self._delete_orphan_device_interfaces(
                device_id=device_id,
                desired_names=desired_names,
                warnings=state.warnings,
            )

        state.ip_address_map = await self._create_ip_addresses(
            interfaces=interfaces,
            warnings=state.warnings,
            add_prefixes_automatically=add_prefixes_automatically,
        )

        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 2: CREATE OR UPDATE INTERFACES ====")
        logger.info("=" * 80)
        for interface in interfaces:
            await self._process_one_interface(
                device_id=device_id,
                interface=interface,
                state=state,
                device_location_id=device_location_id,
            )

        logger.info("\n==== STEP 2.5: ASSIGN LAG MEMBERSHIPS ====")
        await self._assign_lag_memberships(
            device_id=device_id,
            interfaces=interfaces,
            state=state,
        )

        if state.primary_ipv4_id:
            await self._set_primary_ipv4(
                device_id=device_id,
                primary_ipv4_id=state.primary_ipv4_id,
                warnings=state.warnings,
            )

        return state.to_result()

    async def _process_one_interface(
        self,
        *,
        device_id: str,
        interface: dict[str, Any],
        state: InterfaceUpdateState,
        device_location_id: str | None = None,
    ) -> None:
        try:
            logger.info("\n--- Processing interface: %s ---", interface["name"])
            interface_id, was_updated = await self._create_or_update_interface(
                device_id=device_id,
                interface=interface,
                warnings=state.warnings,
                device_location_id=device_location_id,
            )
            logger.info("Interface ID returned: %s", interface_id)

            if not interface_id:
                return

            iface_name = interface["name"]
            state.interface_id_map[iface_name] = interface_id
            if was_updated:
                if iface_name not in state.updated_interfaces:
                    state.updated_interfaces.append(iface_name)
            elif iface_name not in state.created_interfaces:
                state.created_interfaces.append(iface_name)

            if interface_id not in state.cleaned_interfaces:
                logger.info("Cleaning existing IPs from interface %s", iface_name)
                await self._clean_interface_ips(
                    interface_id=interface_id,
                    interface_name=iface_name,
                    warnings=state.warnings,
                )
                state.cleaned_interfaces.add(interface_id)
            else:
                logger.info("Interface %s already cleaned", iface_name)

            logger.info(
                "\n==== STEP 3: ASSIGN IP(S) TO INTERFACE %s ====",
                iface_name,
            )
            logger.info("Interface ID: %s", interface_id)
            await self._assign_ips_for_interface(
                interface=interface,
                interface_id=interface_id,
                state=state,
            )
        except Exception as e:
            error_msg = str(e)
            state.failed_interfaces.append(interface["name"])
            state.warnings.append(
                f"Interface {interface['name']}: Failed to process interface: {error_msg}"
            )
            logger.error("Error processing interface %s: %s", interface["name"], error_msg)
