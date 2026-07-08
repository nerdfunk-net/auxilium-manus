"""Nautobot source operations — preview, field metadata, resolve, analyze."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_inventory_service,
    nautobot_credentials_from_body,
    nautobot_credentials_from_query,
)
from models.sources_nautobot import (
    DeviceAttributesRequest,
    DeviceDetailsRequest,
    DeviceSearchRequest,
    DeviceSearchResponse,
    DeviceSummary,
    GroupsResponse,
    InventoryPreviewRequest,
    InventoryPreviewResponse,
    RenameGroupRequest,
    RenameGroupResponse,
)
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.source_service import NautobotSourceService
from utils.inventory_converter import convert_saved_inventory_to_operations

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources/nautobot", tags=["sources-nautobot"])


def _build_source_service(
    credentials: NautobotCredentials,
    persistence: InventoryService | None = None,
) -> NautobotSourceService:
    return NautobotSourceService(
        nautobot=service_factory.get_nautobot_app_service(),
        credentials=credentials,
        cache_service=service_factory.build_cache_service(),
        persistence_service=persistence,
    )


@router.get("/get-all-groups", response_model=GroupsResponse)
async def get_all_groups(
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> GroupsResponse:
    try:
        groups = persistence.get_all_groups(current_user.username)
        return GroupsResponse(groups=groups)
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to fetch inventory groups: ", exc)


@router.post("/rename-group", response_model=RenameGroupResponse)
async def rename_group(
    request: RenameGroupRequest,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> RenameGroupResponse:
    try:
        result = persistence.rename_group(
            old_path=request.old_path,
            new_name=request.new_name,
            username=current_user.username,
        )
        return RenameGroupResponse(
            updated_count=result["updated_count"],
            new_path=result["new_path"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to rename group: ", exc)


@router.post("/preview", response_model=InventoryPreviewResponse)
async def preview_inventory(
    request: InventoryPreviewRequest,
    _: User = Depends(get_current_user),
) -> InventoryPreviewResponse:
    credentials = nautobot_credentials_from_body(request)
    source_service = _build_source_service(credentials)
    try:
        if not request.operations:
            return InventoryPreviewResponse(
                devices=[],
                total_count=0,
                operations_executed=0,
            )
        devices, operations_count = await source_service.preview_inventory(request.operations)
        return InventoryPreviewResponse(
            devices=devices,
            total_count=len(devices),
            operations_executed=operations_count,
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to preview Nautobot source: ", exc)


@router.post("/devices/search", response_model=DeviceSearchResponse)
async def search_devices(
    request: DeviceSearchRequest,
    _: User = Depends(get_current_user),
) -> DeviceSearchResponse:
    credentials = nautobot_credentials_from_body(request)
    source_service = _build_source_service(credentials)
    try:
        devices = await source_service.search_devices_by_name(request.search, request.limit)
        return DeviceSearchResponse(
            devices=[
                DeviceSummary(
                    id=device.id,
                    name=device.name,
                    primary_ip4=device.primary_ip4,
                    platform=device.platform,
                    network_driver=device.platform_network_driver,
                )
                for device in devices
            ]
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to search Nautobot devices: ", exc)


@router.post("/devices/details")
async def get_device_details(
    request: DeviceDetailsRequest,
    _: User = Depends(get_current_user),
) -> dict:
    credentials = nautobot_credentials_from_body(request)
    source_service = _build_source_service(credentials)
    try:
        return await source_service.get_device_details(request.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to fetch device details: ", exc)


@router.post("/devices/attributes")
async def get_device_attributes(
    request: DeviceAttributesRequest,
    _: User = Depends(get_current_user),
) -> dict:
    credentials = nautobot_credentials_from_body(request)
    source_service = _build_source_service(credentials)
    try:
        return await source_service.get_device_attributes(
            request.device_id, request.list_of_attributes
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to fetch device attributes: ", exc)


@router.get("/field-options")
async def get_field_options(_: User = Depends(get_current_user)) -> dict:
    return {
        "fields": [
            {"value": "name", "label": "Device Name"},
            {"value": "location", "label": "Location"},
            {"value": "role", "label": "Role"},
            {"value": "status", "label": "Status"},
            {"value": "tag", "label": "Tag"},
            {"value": "device_type", "label": "Device Type"},
            {"value": "manufacturer", "label": "Manufacturer"},
            {"value": "platform", "label": "Platform"},
            {"value": "has_primary", "label": "Has Primary"},
            {"value": "ip_prefix", "label": "IP Prefix"},
            {"value": "custom_fields", "label": "Custom Fields..."},
        ],
        "operators": [
            {"value": "equals", "label": "Equals"},
            {"value": "not_equals", "label": "Not Equals"},
            {"value": "contains", "label": "Contains"},
            {"value": "not_contains", "label": "Not Contains"},
        ],
        "logical_operations": [
            {"value": "AND", "label": "AND"},
            {"value": "OR", "label": "OR"},
            {"value": "NOT", "label": "NOT"},
        ],
    }


@router.get("/custom-fields")
async def get_custom_fields(
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        source_service = _build_source_service(credentials)
        custom_fields = await source_service.get_custom_fields()
        return {"custom_fields": custom_fields}
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get custom fields: ", exc)


@router.get("/field-values/{field_name}")
async def get_field_values(
    field_name: str,
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        source_service = _build_source_service(credentials)
        field_values = await source_service.get_field_values(field_name)
        return {
            "field": field_name,
            "values": field_values,
            "input_type": "select" if field_values else "text",
        }
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get field values: ", exc)


@router.get("/resolve-devices/{inventory_id}")
async def resolve_inventory_to_devices(
    inventory_id: int,
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> dict:
    try:
        inventory = persistence.get_inventory(inventory_id, username=current_user.username)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory with ID {inventory_id} not found",
            )

        conditions = inventory.get("conditions", [])
        if not conditions:
            return {
                "device_ids": [],
                "device_count": 0,
                "inventory_id": inventory_id,
                "inventory_name": inventory.get("name", ""),
            }

        source_service = _build_source_service(credentials, persistence)
        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await source_service.preview_inventory(operations)
        device_ids = [device.id for device in devices]
        return {
            "device_ids": device_ids,
            "device_count": len(device_ids),
            "inventory_id": inventory_id,
            "inventory_name": inventory.get("name", ""),
        }
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(
            logger,
            "Failed to resolve inventory",
            exc,
            extra={"inventory_id": inventory_id},
        )


@router.get("/resolve-devices/detailed/{inventory_id}")
async def resolve_inventory_to_devices_detailed(
    inventory_id: int,
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> dict:
    try:
        inventory = persistence.get_inventory(inventory_id, username=current_user.username)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory with ID {inventory_id} not found",
            )

        conditions = inventory.get("conditions", [])
        if not conditions:
            return {
                "devices": [],
                "device_details": [],
                "device_count": 0,
                "inventory_id": inventory_id,
                "inventory_name": inventory.get("name", ""),
            }

        source_service = _build_source_service(credentials, persistence)
        operations = convert_saved_inventory_to_operations(conditions)
        devices, _ = await source_service.preview_inventory(operations)

        device_details = []
        device_list = []
        for device in devices:
            try:
                detail = await source_service.device_query_service.get_device_details(
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
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(
            logger,
            "Failed to resolve detailed inventory",
            exc,
            extra={"inventory_id": inventory_id},
        )


@router.get("/{inventory_id}/analyze")
async def analyze_inventory(
    inventory_id: int,
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> dict:
    try:
        source_service = _build_source_service(credentials, persistence)
        return await source_service.analyze_inventory(inventory_id, current_user.username)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        if "Access denied" in message:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to analyze inventory: ", exc)
