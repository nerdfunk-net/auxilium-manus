"""Facade for Nautobot device-source operations (preview, resolve, analyze)."""

from __future__ import annotations

import logging
from typing import Any

from models.sources_nautobot import DeviceInfo, LogicalOperation
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.query import DeviceQueryService
from services.sources.nautobot.evaluator import NautobotSourceEvaluator
from services.sources.nautobot.export_service import NautobotSourceExportService
from services.sources.nautobot.metadata_service import NautobotSourceMetadataService
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.query_service import NautobotSourceQueryService

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
        self.query_service = NautobotSourceQueryService(nautobot, credentials, cache_service)
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

    async def analyze_inventory(self, inventory_id: int, username: str) -> dict[str, Any]:
        from utils.inventory_converter import convert_saved_inventory_to_operations

        if self._persistence_service is None:
            raise ValueError("Persistence service is not configured")

        inventory = self._persistence_service.get_inventory(inventory_id, username=username)
        if not inventory:
            raise ValueError(f"Inventory with ID {inventory_id} not found")

        conditions = inventory.get("conditions", [])
        if not conditions:
            return {
                "locations": [],
                "tags": [],
                "custom_fields": {},
                "statuses": [],
                "roles": [],
                "device_count": 0,
            }

        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await self.preview_inventory(operations)
        return await self.export_service.analyze_devices(devices)

    async def search_devices_by_name(
        self, name_filter: str, limit: int = 20
    ) -> list[DeviceInfo]:
        """Return devices whose name contains ``name_filter`` (case-insensitive)."""
        devices = await self.query_service._query_devices_by_name(
            name_filter, use_contains=True
        )
        return devices[:limit]

    async def get_device_details(self, device_id: str) -> dict[str, Any]:
        """Return full Nautobot device details for a single device."""
        return await self.device_query_service.get_device_details(device_id, use_cache=True)

    async def get_custom_fields(self) -> list[dict[str, Any]]:
        return await self.metadata_service.get_custom_fields()

    async def get_field_values(self, field_name: str) -> list[dict[str, str]]:
        return await self.metadata_service.get_field_values(field_name)
