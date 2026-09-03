"""Facade for Nautobot device-source operations (preview, resolve, analyze)."""

from __future__ import annotations

import logging
from typing import Any

from models.sources_nautobot import DeviceInfo, InventoryPreviewResponse, LogicalOperation
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.query import DeviceQueryService
from services.sources.nautobot.evaluator import NautobotSourceEvaluator
from services.sources.nautobot.export_service import NautobotSourceExportService
from services.sources.nautobot.metadata_service import NautobotSourceMetadataService
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.query_service import NautobotSourceQueryService
from utils.inventory_converter import convert_saved_inventory_to_operations

logger = logging.getLogger(__name__)


class NautobotSourceService:
    def __init__(
        self,
        nautobot: NautobotService,
        credentials: NautobotCredentials,
        cache_service=None,
        persistence_service: InventoryService | None = None,
        device_ttl: int = 1800,
    ) -> None:
        self.query_service = NautobotSourceQueryService(
            nautobot, credentials, cache_service, bulk_ttl=device_ttl
        )
        self.evaluator = NautobotSourceEvaluator(self.query_service)
        self.metadata_service = NautobotSourceMetadataService(nautobot, credentials)
        self.device_query_service = DeviceQueryService(
            nautobot, credentials, cache_service, device_ttl
        )
        self.export_service = NautobotSourceExportService(self.device_query_service)
        self._persistence_service = persistence_service

    async def preview_inventory(
        self, operations: list[LogicalOperation]
    ) -> tuple[list[DeviceInfo], int]:
        if not operations:
            all_devices = await self.query_service._query_all_devices()
            return all_devices, 0

        result_devices: set[str] = set()
        all_devices_data: dict[str, DeviceInfo] = {}
        operations_count = 0

        for operation in operations:
            operation_result, op_count, devices_data = await self.evaluator._execute_operation(
                operation
            )
            operations_count += op_count
            all_devices_data.update(devices_data)

            op_type = operation.operation_type.upper()
            if not result_devices:
                result_devices = set() if op_type == "NOT" else operation_result
            elif op_type == "NOT":
                result_devices = result_devices.difference(operation_result)
            else:
                result_devices = result_devices.intersection(operation_result)

        result_list = [
            all_devices_data[device_id]
            for device_id in result_devices
            if device_id in all_devices_data
        ]
        return result_list, operations_count

    async def resolve_devices_by_ids(self, device_ids: list[str]) -> list[DeviceInfo]:
        """Resolve an explicit list of Nautobot device IDs (static inventory) to DeviceInfo."""
        all_devices = await self.query_service._query_all_devices()
        wanted = set(device_ids)
        return [device for device in all_devices if device.id in wanted]

    async def analyze_inventory(self, inventory_id: int, username: str) -> dict[str, Any]:
        from utils.inventory_converter import convert_saved_inventory_to_operations

        if self._persistence_service is None:
            raise ValueError("Persistence service is not configured")

        inventory = self._persistence_service.get_inventory(inventory_id, username=username)
        if not inventory:
            raise ValueError(f"Inventory with ID {inventory_id} not found")

        empty_analysis = {
            "locations": [],
            "tags": [],
            "custom_fields": {},
            "statuses": [],
            "roles": [],
            "device_count": 0,
        }

        if inventory.get("inventory_type") == "static":
            device_ids = inventory.get("device_ids") or []
            if not device_ids:
                return empty_analysis
            devices = await self.resolve_devices_by_ids(device_ids)
            return await self.export_service.analyze_devices(devices)

        conditions = inventory.get("conditions", [])
        if not conditions:
            return empty_analysis

        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await self.preview_inventory(operations)
        return await self.export_service.analyze_devices(devices)

    async def resolve_saved_inventory_devices_by_id(
        self, inventory_id: int, username: str | None
    ) -> list[DeviceInfo]:
        """Load a saved inventory by id (RBAC-checked against *username*) and
        resolve it to devices — the runtime counterpart of
        ``analyze_inventory``, used by the ``get-nautobot-devices`` step when
        its inventory is chosen from a run parameter instead of the canvas.

        Raises ``ValueError`` if the inventory does not exist; ``PermissionError``
        (from the persistence layer) if it is private to another user.
        """
        from utils.inventory_converter import convert_saved_inventory_to_operations

        if self._persistence_service is None:
            raise ValueError("Persistence service is not configured")

        inventory = self._persistence_service.get_inventory(inventory_id, username=username)
        if not inventory:
            raise ValueError(f"Inventory with ID {inventory_id} not found")

        if inventory.get("inventory_type") == "static":
            device_ids = inventory.get("device_ids") or []
            return await self.resolve_devices_by_ids(device_ids) if device_ids else []

        conditions = inventory.get("conditions", [])
        if not conditions:
            return []
        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await self.preview_inventory(operations)
        return devices

    async def search_devices_by_name(self, name_filter: str, limit: int = 20) -> list[DeviceInfo]:
        """Return devices whose name contains ``name_filter`` (case-insensitive)."""
        devices = await self.query_service._query_devices_by_name(name_filter, use_contains=True)
        return devices[:limit]

    async def get_device_details(self, device_id: str) -> dict[str, Any]:
        """Return full Nautobot device details for a single device."""
        return await self.device_query_service.get_device_details(device_id, use_cache=True)

    async def get_device_attributes(
        self, device_id: str, list_of_attributes: list[str] | None = None
    ) -> dict[str, Any]:
        """Return the ``nautobot`` attribute bag for a single device."""
        return await self.device_query_service.get_device_attributes(
            device_id, list_of_attributes, use_cache=True
        )

    async def refresh_bulk_device_cache(self) -> int:
        """(Re)populate the Redis bulk device cache. Returns devices written."""
        return await self.query_service.refresh_bulk_cache()

    async def get_custom_fields(self) -> list[dict[str, Any]]:
        return await self.metadata_service.get_custom_fields()

    async def get_field_values(self, field_name: str) -> list[dict[str, str]]:
        return await self.metadata_service.get_field_values(field_name)

    async def resolve_saved_inventory_ids(self, inventory: dict, inventory_id: int) -> dict:
        """Resolve a saved inventory (static or dynamic) to a list of device ids."""
        if inventory.get("inventory_type") == "static":
            static_ids = inventory.get("device_ids") or []
            if not static_ids:
                return {
                    "device_ids": [],
                    "device_count": 0,
                    "inventory_id": inventory_id,
                    "inventory_name": inventory.get("name", ""),
                }
            devices = await self.resolve_devices_by_ids(static_ids)
            device_ids = [device.id for device in devices]
            return {
                "device_ids": device_ids,
                "device_count": len(device_ids),
                "inventory_id": inventory_id,
                "inventory_name": inventory.get("name", ""),
            }

        conditions = inventory.get("conditions", [])
        if not conditions:
            return {
                "device_ids": [],
                "device_count": 0,
                "inventory_id": inventory_id,
                "inventory_name": inventory.get("name", ""),
            }

        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await self.preview_inventory(operations)
        device_ids = [device.id for device in devices]
        return {
            "device_ids": device_ids,
            "device_count": len(device_ids),
            "inventory_id": inventory_id,
            "inventory_name": inventory.get("name", ""),
        }

    async def resolve_saved_inventory_detailed(self, inventory: dict, inventory_id: int) -> dict:
        """Resolve a saved inventory (static or dynamic) to full device detail records."""
        if inventory.get("inventory_type") == "static":
            static_ids = inventory.get("device_ids") or []
            if not static_ids:
                return {
                    "devices": [],
                    "device_details": [],
                    "device_count": 0,
                    "inventory_id": inventory_id,
                    "inventory_name": inventory.get("name", ""),
                }
            devices = await self.resolve_devices_by_ids(static_ids)
        else:
            conditions = inventory.get("conditions", [])
            if not conditions:
                return {
                    "devices": [],
                    "device_details": [],
                    "device_count": 0,
                    "inventory_id": inventory_id,
                    "inventory_name": inventory.get("name", ""),
                }

            operations = convert_saved_inventory_to_operations(conditions)
            devices, _ = await self.preview_inventory(operations)

        device_details = []
        device_list = []
        for device in devices:
            try:
                detail = await self.device_query_service.get_device_details(
                    device_id=device.id,
                    use_cache=True,
                )
                device_details.append(detail)
                primary_ip4 = detail.get("primary_ip4")
                address = primary_ip4.get("address") if isinstance(primary_ip4, dict) else None
                device_list.append(
                    {"id": detail.get("id"), "name": detail.get("name"), "primary_ip4": address}
                )
            except Exception as exc:
                logger.error(
                    "Error fetching details for device %s (%s): %s",
                    device.id,
                    device.name,
                    exc,
                )

        return {
            "devices": device_list,
            "device_details": device_details,
            "device_count": len(device_list),
            "inventory_id": inventory_id,
            "inventory_name": inventory.get("name", ""),
        }

    async def resolve_saved_inventory_devices(self, inventory: dict) -> InventoryPreviewResponse:
        """Resolve a saved inventory (either type) to full DeviceInfo records."""
        if inventory.get("inventory_type") == "static":
            devices = await self.resolve_devices_by_ids(inventory.get("device_ids") or [])
            return InventoryPreviewResponse(
                devices=devices, total_count=len(devices), operations_executed=0
            )

        conditions = inventory.get("conditions", [])
        if not conditions:
            return InventoryPreviewResponse(devices=[], total_count=0, operations_executed=0)

        operations = convert_saved_inventory_to_operations(conditions)
        devices, operations_executed = await self.preview_inventory(operations)
        return InventoryPreviewResponse(
            devices=devices,
            total_count=len(devices),
            operations_executed=operations_executed,
        )
