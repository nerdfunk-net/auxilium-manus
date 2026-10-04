"""Interface-record operations of the interface workflow (create, patch, LAG, primary IP)."""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.devices.interface_workflow.base import InterfaceOpsBase
from services.nautobot.devices.interface_workflow.payload import (
    build_interface_payload,
    normalize_interface_type,
    resolve_tagged_vlan_ids,
    resolve_untagged_vlan_id,
)
from services.nautobot.devices.interface_workflow.state import InterfaceUpdateState

logger = logging.getLogger(__name__)


class InterfaceRecordOps(InterfaceOpsBase):
    async def _assign_lag_memberships(
        self,
        *,
        device_id: str,
        interfaces: list[dict[str, Any]],
        state: InterfaceUpdateState,
    ) -> None:
        """Wire each member interface's ``lag`` to its port-channel's UUID.

        Runs after every interface in the batch has already been created or
        updated (``state.interface_id_map`` is fully populated by then), since
        a member can reference a port-channel that hadn't been processed yet
        — Batfish's JSON key order isn't guaranteed to put it first.
        """
        for interface in interfaces:
            member_name = (interface.get("name") or "").strip()
            raw_lag = interface.get("lag")
            if not member_name or not raw_lag or raw_lag == "none":
                continue

            member_id = state.interface_id_map.get(member_name)
            if not member_id:
                # This interface itself failed to create/update — nothing to patch.
                continue

            lag_name = str(raw_lag)
            if is_valid_uuid(lag_name):
                lag_id: str | None = lag_name
            elif lag_name == member_name:
                state.warnings.append(
                    f"Interface {member_name}: lag cannot reference itself — omitting"
                )
                continue
            else:
                lag_id = state.interface_id_map.get(lag_name)
                if not lag_id:
                    lag_id = await self.common.resolve_interface_by_name(
                        device_id=device_id, interface_name=lag_name
                    )
                if not lag_id:
                    state.warnings.append(
                        f"Interface {member_name}: lag interface '{lag_name}' not found — omitting"
                    )
                    continue

            try:
                await self.nautobot.rest_request(
                    endpoint=f"dcim/interfaces/{member_id}/",
                    method="PATCH",
                    data={"lag": {"id": lag_id}},
                )
                logger.info("  Set lag for %s -> %s (%s)", member_name, lag_name, lag_id)
            except Exception as e:
                state.warnings.append(
                    f"Interface {member_name}: failed to set lag '{lag_name}': {e}"
                )
                logger.error("Error setting lag for %s: %s", member_name, e)

    async def _create_or_update_interface(
        self,
        device_id: str,
        interface: dict[str, Any],
        warnings: list[str],
        device_location_id: str | None = None,
    ) -> tuple[str | None, bool]:
        """
        Create or update a single interface.

        Args:
            device_id: Device UUID
            interface: Interface specification
            warnings: List to append warnings to
            device_location_id: Device's Nautobot location UUID, if known —
                used to scope untagged_vlan resolution/creation

        Returns:
            Tuple of (interface UUID if successful, was_updated flag)
        """
        interface_type = normalize_interface_type(interface, warnings)
        if interface_type is None:
            return None, False

        # Resolve status to UUID — use "or" fallback so empty string also defaults to "active"
        interface_status = interface.get("status") or "active"
        interface_status_id = await self.common.resolve_status_id(
            interface_status, "dcim.interface"
        )
        untagged_vlan_id = await resolve_untagged_vlan_id(
            common=self.common,
            interface=interface,
            device_location_id=device_location_id,
            warnings=warnings,
        )
        tagged_vlan_ids = await resolve_tagged_vlan_ids(
            common=self.common,
            interface=interface,
            device_location_id=device_location_id,
            warnings=warnings,
        )
        interface_payload = build_interface_payload(
            device_id=device_id,
            interface=interface,
            interface_type=interface_type,
            interface_status_id=interface_status_id,
            untagged_vlan_id=untagged_vlan_id,
            tagged_vlan_ids=tagged_vlan_ids,
        )

        existing_id = await self.common.resolve_interface_by_name(
            device_id=device_id,
            interface_name=interface["name"],
        )
        if existing_id:
            return await self._patch_existing_interface(
                existing_id, interface, interface_payload, warnings
            )

        return await self._create_interface_with_race_fallback(
            device_id=device_id,
            interface=interface,
            interface_payload=interface_payload,
            warnings=warnings,
        )

    async def _patch_existing_interface(
        self,
        existing_id: str,
        interface: dict[str, Any],
        interface_payload: dict[str, Any],
        warnings: list[str],
    ) -> tuple[str | None, bool]:
        patch_payload = {k: v for k, v in interface_payload.items() if k not in ("name", "device")}
        try:
            await self.nautobot.rest_request(
                endpoint=f"dcim/interfaces/{existing_id}/",
                method="PATCH",
                data=patch_payload,
            )
            logger.info("Updated interface %s with ID: %s", interface["name"], existing_id)
            return existing_id, True
        except Exception as patch_error:
            warnings.append(f"Interface {interface['name']}: Failed to update: {patch_error}")
            return existing_id, True

    async def _create_interface_with_race_fallback(
        self,
        *,
        device_id: str,
        interface: dict[str, Any],
        interface_payload: dict[str, Any],
        warnings: list[str],
    ) -> tuple[str | None, bool]:
        logger.debug("Creating interface with payload: %s", interface_payload)

        try:
            interface_response = await self.nautobot.rest_request(
                endpoint="dcim/interfaces/",
                method="POST",
                data=interface_payload,
            )

            if interface_response and "id" in interface_response:
                interface_id = interface_response["id"]
                logger.info("Created interface %s with ID: %s", interface["name"], interface_id)
                return interface_id, False

        except Exception as create_error:
            if "must make a unique set" in str(create_error).lower():
                interface_id = await self.common.resolve_interface_by_name(
                    device_id=device_id,
                    interface_name=interface["name"],
                )
                if interface_id:
                    patch_payload = {
                        k: v for k, v in interface_payload.items() if k not in ("name", "device")
                    }
                    try:
                        await self.nautobot.rest_request(
                            endpoint=f"dcim/interfaces/{interface_id}/",
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
                    f"Interface {interface['name']}: Failed to create interface: "
                    f"{str(create_error)}"
                )

        return None, False

    async def _set_primary_ipv4(
        self,
        device_id: str,
        primary_ipv4_id: str,
        warnings: list[str],
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
                endpoint=f"dcim/devices/{device_id}/",
                method="PATCH",
                data=update_payload,
            )
            logger.info("Set primary IPv4 to %s", primary_ipv4_id)
        except Exception as e:
            warnings.append(f"Failed to set primary IPv4: {str(e)}")
