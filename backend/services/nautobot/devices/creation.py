"""
Device creation service for Nautobot.

Handles the orchestrated workflow for creating a device (optionally with rack
placement, virtual chassis membership, and interfaces) in Nautobot. Ported from
cockpit's ``services/nautobot/devices/creation.py``, adapted to this codebase's
dependency-injection convention (an injected ``nautobot_service``, matching
``DeviceUpdateService``) and without cockpit's audit-log integration.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.nautobot import NautobotService
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.interface_workflow import InterfaceManagerService
from services.nautobot.devices.types import AddDeviceRequest

logger = logging.getLogger(__name__)


class DeviceCreationService:
    """Service for creating devices in Nautobot."""

    def __init__(self, nautobot_service: NautobotService):
        self.nautobot = nautobot_service
        self.common = DeviceCommonService(nautobot_service)
        self.interface_manager = InterfaceManagerService(nautobot_service)

    async def create_device(self, request: AddDeviceRequest) -> dict[str, Any]:
        """Resolve names to UUIDs, then create the device (+ VC + interfaces).

        Returns a dict with ``device_id``, ``device_name``, ``device`` (raw REST
        response), ``interfaces_created``, ``interfaces_failed``, ``warnings``,
        ``dry_run``, and ``errors``.

        Raises ``ValueError`` for unresolvable required fields, ``NautobotAPIError``
        for Nautobot REST failures.
        """
        request = await self._resolve_request_names_to_ids(request)

        if request.dry_run:
            return await self._validate_dry_run(request)

        device_id, device_response = await self._create_device(request)

        warnings: list[str] = []

        if request.new_virtual_chassis_name:
            await self._create_and_join_virtual_chassis(
                device_id, request.new_virtual_chassis_name, warnings
            )
        elif request.virtual_chassis_id:
            await self._join_virtual_chassis(
                device_id, request.virtual_chassis_id, request.name, warnings
            )

        interfaces_created = 0
        interfaces_failed = 0
        if request.interfaces:
            result = await self.interface_manager.update_device_interfaces(
                device_id=device_id,
                interfaces=request.interfaces,
                add_prefixes_automatically=request.add_prefix,
            )
            interfaces_created = result.interfaces_created + result.interfaces_updated
            interfaces_failed = result.interfaces_failed
            warnings.extend(result.warnings)

        return {
            "success": True,
            "dry_run": False,
            "device_id": device_id,
            "device_name": request.name,
            "device": device_response,
            "interfaces_created": interfaces_created,
            "interfaces_failed": interfaces_failed,
            "warnings": warnings,
            "errors": [],
        }

    async def _resolve_request_names_to_ids(self, request: AddDeviceRequest) -> AddDeviceRequest:
        """Resolve human-readable names to Nautobot UUIDs.

        Fields already holding a valid UUID pass through unchanged, so this is safe
        whether the caller sends names or UUIDs.
        """
        updates: dict[str, Any] = {}

        if request.device_type and not is_valid_uuid(request.device_type):
            device_type_id = await self.common.resolve_device_type_id(request.device_type)
            if not device_type_id:
                raise ValueError(f"Device type '{request.device_type}' not found in Nautobot")
            updates["device_type"] = device_type_id

        if request.role and not is_valid_uuid(request.role):
            role_id = await self.common.resolve_role_id(request.role)
            if not role_id:
                raise ValueError(f"Role '{request.role}' not found in Nautobot")
            updates["role"] = role_id

        if request.status and not is_valid_uuid(request.status):
            status_id = await self.common.resolve_status_id(
                request.status, content_type="dcim.device"
            )
            if not status_id:
                raise ValueError(f"Status '{request.status}' not found in Nautobot")
            updates["status"] = status_id

        if request.location and not is_valid_uuid(request.location):
            location_id = await self.common.resolve_location_id(request.location)
            if not location_id:
                raise ValueError(f"Location '{request.location}' not found in Nautobot")
            updates["location"] = location_id

        if request.platform and not is_valid_uuid(request.platform):
            platform_id = await self.common.resolve_platform_id(request.platform)
            if platform_id:
                updates["platform"] = platform_id
            else:
                logger.warning("Platform '%s' not found in Nautobot — skipping", request.platform)
                updates["platform"] = None

        if updates:
            return request.model_copy(update=updates)
        return request

    async def _validate_dry_run(self, request: AddDeviceRequest) -> dict[str, Any]:
        """Validate a request against Nautobot without creating anything."""
        errors: list[str] = []

        try:
            existing = await self.nautobot.rest_request(
                f"dcim/devices/?name={request.name}&limit=1"
            )
            if existing.get("count", 0) > 0:
                errors.append(f"A device named '{request.name}' already exists in Nautobot")
        except Exception as exc:
            logger.warning("Dry run: could not check device existence: %s", exc)

        uuid_checks = [
            (
                "device_type",
                f"dcim/device-types/?id={request.device_type}&limit=1",
                "Device type",
            ),
            ("role", f"extras/roles/?id={request.role}&limit=1", "Role"),
            ("status", f"extras/statuses/?id={request.status}&limit=1", "Status"),
            ("location", f"dcim/locations/?id={request.location}&limit=1", "Location"),
        ]
        for field, endpoint, label in uuid_checks:
            try:
                result = await self.nautobot.rest_request(endpoint)
                if result.get("count", 0) == 0:
                    errors.append(f"{label} ID '{getattr(request, field)}' not found in Nautobot")
            except Exception as exc:
                logger.warning("Dry run: could not validate %s: %s", label, exc)

        if request.platform:
            try:
                result = await self.nautobot.rest_request(
                    f"dcim/platforms/?id={request.platform}&limit=1"
                )
                if result.get("count", 0) == 0:
                    errors.append(f"Platform ID '{request.platform}' not found in Nautobot")
            except Exception as exc:
                logger.warning("Dry run: could not validate platform: %s", exc)

        success = len(errors) == 0
        return {
            "success": success,
            "dry_run": True,
            "device_id": None,
            "device_name": request.name,
            "device": None,
            "interfaces_created": 0,
            "interfaces_failed": 0,
            "warnings": [],
            "errors": errors,
        }

    async def _create_device(self, request: AddDeviceRequest) -> tuple[str, dict[str, Any]]:
        """POST dcim/devices/ with resolved UUIDs and optional attributes/rack."""
        device_payload: dict[str, Any] = {
            "name": request.name,
            "device_type": request.device_type,
            "role": request.role,
            "location": request.location,
            "status": request.status,
        }

        if request.platform:
            device_payload["platform"] = request.platform
        if request.software_version:
            device_payload["software_version"] = request.software_version
        if request.serial:
            device_payload["serial"] = request.serial
        if request.asset_tag:
            device_payload["asset_tag"] = request.asset_tag
        if request.tags:
            device_payload["tags"] = request.tags
        if request.custom_fields:
            device_payload["custom_fields"] = request.custom_fields
        if request.rack:
            rack_id = request.rack
            if not is_valid_uuid(rack_id):
                rack_id = await self.common.resolve_rack_id(rack_id)
                if not rack_id:
                    logger.warning("Rack '%s' not found — skipping rack placement", request.rack)
            if rack_id:
                device_payload["rack"] = rack_id
                if request.face:
                    device_payload["face"] = request.face.lower()
                if request.position is not None:
                    device_payload["position"] = request.position

        device_response = await self.nautobot.rest_request(
            endpoint="dcim/devices/", method="POST", data=device_payload
        )

        if not device_response or "id" not in device_response:
            raise NautobotAPIError(
                f"Failed to create device '{request.name}': no device ID returned"
            )

        return device_response["id"], device_response

    @staticmethod
    def _extract_vc_position_from_name(device_name: str) -> int | None:
        """Extract a VC position from the device name when it contains a ':'.

        Examples: "lab-004:4" -> 4, "router1" -> None, "router:abc" -> None.
        """
        if ":" not in device_name:
            return None
        suffix = device_name.split(":", 1)[1]
        match = re.match(r"^(\d+)", suffix)
        if match:
            return int(match.group(1))
        return None

    async def _join_virtual_chassis(
        self,
        device_id: str,
        vc_id: str,
        device_name: str,
        warnings: list[str],
    ) -> None:
        """Add the newly created device to an existing virtual chassis.

        Position resolution: a leading integer after ':' in the device name (e.g.
        "lab-004:4" -> 4) takes priority; otherwise falls back to
        max(existing positions) + 1.
        """
        try:
            name_position = self._extract_vc_position_from_name(device_name)
            if name_position is not None:
                next_position = name_position
            else:
                members_resp = await self.nautobot.rest_request(
                    f"dcim/devices/?virtual_chassis={vc_id}&limit=100"
                )
                positions = [
                    m.get("vc_position")
                    for m in members_resp.get("results", [])
                    if m.get("vc_position") is not None
                ]
                next_position = (max(positions) + 1) if positions else 1

            await self.nautobot.rest_request(
                f"dcim/devices/{device_id}/",
                method="PATCH",
                data={
                    "virtual_chassis": {"id": vc_id},
                    "vc_position": next_position,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to add device %s to virtual chassis %s: %s",
                device_id,
                vc_id,
                exc,
            )
            warnings.append(f"Could not join virtual chassis: {exc}")

    async def _create_and_join_virtual_chassis(
        self,
        device_id: str,
        vc_name: str,
        warnings: list[str],
    ) -> None:
        """Create a new virtual chassis and add the device as master at position 1."""
        try:
            vc = await self.nautobot.rest_request(
                "dcim/virtual-chassis/",
                method="POST",
                data={"name": vc_name},
            )
            vc_id = vc["id"]

            await self.nautobot.rest_request(
                f"dcim/devices/{device_id}/",
                method="PATCH",
                data={"virtual_chassis": {"id": vc_id}, "vc_position": 1},
            )

            await self.nautobot.rest_request(
                f"dcim/virtual-chassis/{vc_id}/",
                method="PATCH",
                data={"master": {"id": device_id}},
            )
        except Exception as exc:
            logger.warning(
                "Failed to create virtual chassis '%s' for device %s: %s",
                vc_name,
                device_id,
                exc,
            )
            warnings.append(f"Could not create virtual chassis '{vc_name}': {exc}")
