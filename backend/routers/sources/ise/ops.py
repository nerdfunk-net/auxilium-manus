"""Cisco ISE network device CRUD and connectivity check, per configured source."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_ise_source_config_service
from models.ise import (
    ISEDeviceGroupChildCreateRequest,
    ISEDeviceGroupResponse,
    ISEDeviceGroupRootCreateRequest,
    ISEDeviceGroupUpdateRequest,
    ISELocationCreateRequest,
    ISELocationResponse,
    ISENetworkDeviceCreate,
    ISENetworkDeviceListResponse,
    ISENetworkDeviceUpdate,
    ISETestConnectionResponse,
)
from services.ise.common.exceptions import (
    ISEAPIError,
    ISENotFoundError,
    ISEValidationError,
)
from services.ise.credentials import ISECredentials
from services.ise.source_config_service import (
    ISESourceConfigService,
    ISESourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/ise/{source_id}",
    tags=["sources-ise"],
    dependencies=[Depends(require_permission("sources.ise", "read"))],
)


def _resolve_credentials(source_id: str, config: ISESourceConfigService) -> ISECredentials:
    try:
        return config.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _resolve_device_service(source_id: str, config: ISESourceConfigService):
    credentials = _resolve_credentials(source_id, config)
    return service_factory.build_ise_network_device_service(credentials)


def _resolve_group_service(source_id: str, config: ISESourceConfigService):
    credentials = _resolve_credentials(source_id, config)
    return service_factory.build_ise_network_device_group_service(credentials)


@router.get("/devices", response_model=ISENetworkDeviceListResponse)
async def list_devices(
    source_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    filter: str | None = Query(default=None, max_length=255),  # noqa: A002
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISENetworkDeviceListResponse:
    device_service = _resolve_device_service(source_id, config)
    try:
        result = await device_service.list_devices(page=page, size=size, filter_=filter)
        search_result = result.get("SearchResult", {})
        return ISENetworkDeviceListResponse(
            total=search_result.get("total", 0),
            resources=search_result.get("resources", []),
            next_page=(search_result.get("nextPage") or {}).get("href"),
        )
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE list devices failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list ISE devices: ", exc)


@router.get("/devices/name/{name}")
async def get_device_by_name(
    source_id: str,
    name: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> dict:
    device_service = _resolve_device_service(source_id, config)
    try:
        return await device_service.get_device_by_name(name)
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE get device by name failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get ISE device: ", exc)


@router.get("/devices/{device_id}")
async def get_device(
    source_id: str,
    device_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> dict:
    device_service = _resolve_device_service(source_id, config)
    try:
        return await device_service.get_device(device_id)
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE get device failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get ISE device: ", exc)


@router.post(
    "/devices",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def create_device(
    source_id: str,
    request: ISENetworkDeviceCreate,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> dict:
    device_service = _resolve_device_service(source_id, config)
    try:
        payload = request.model_dump(exclude_none=True)
        return await device_service.create_device(payload)
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE create device failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create ISE device: ", exc)


@router.put(
    "/devices/{device_id}",
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def update_device(
    source_id: str,
    device_id: str,
    request: ISENetworkDeviceUpdate,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> dict:
    device_service = _resolve_device_service(source_id, config)
    try:
        payload = request.model_dump(exclude_none=True)
        return await device_service.update_device(device_id, payload)
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE update device failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update ISE device: ", exc)


@router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.ise", "delete"))],
)
async def delete_device(
    source_id: str,
    device_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> None:
    device_service = _resolve_device_service(source_id, config)
    try:
        await device_service.delete_device(device_id)
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE delete device failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete ISE device: ", exc)


@router.post("/test-connection", response_model=ISETestConnectionResponse)
async def test_connection(
    source_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISETestConnectionResponse:
    device_service = _resolve_device_service(source_id, config)
    try:
        await device_service.test_connection()
        return ISETestConnectionResponse(success=True, message="Connection successful")
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        return ISETestConnectionResponse(success=False, message=f"Connection failed: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ISE test connection failed: ", exc)


@router.post(
    "/location-groups",
    response_model=ISELocationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def create_location_group(
    source_id: str,
    request: ISELocationCreateRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISELocationResponse:
    group_service = _resolve_group_service(source_id, config)
    try:
        result = await group_service.create_location(
            name=request.name,
            description=request.description,
            parent_group=request.parent_group,
        )
        return ISELocationResponse(
            id=result.get("id"),
            name=result["name"],
            description=request.description,
            parent_group=request.parent_group,
        )
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE create location group failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create ISE location group: ", exc)


@router.post(
    "/network-device-groups/roots",
    response_model=ISEDeviceGroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def create_network_device_group_root(
    source_id: str,
    request: ISEDeviceGroupRootCreateRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISEDeviceGroupResponse:
    group_service = _resolve_group_service(source_id, config)
    try:
        result = await group_service.create_root_group(
            name=request.name, description=request.description
        )
        return ISEDeviceGroupResponse(
            id=result.get("id"),
            name=result["name"],
            description=request.description,
            othername=result["othername"],
        )
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE create root device group failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create ISE root device group: ", exc)


@router.post(
    "/network-device-groups/children",
    response_model=ISEDeviceGroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def create_network_device_group_child(
    source_id: str,
    request: ISEDeviceGroupChildCreateRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISEDeviceGroupResponse:
    group_service = _resolve_group_service(source_id, config)
    try:
        result = await group_service.create_child_group(
            name=request.name,
            description=request.description,
            parent_group=request.parent_group,
        )
        return ISEDeviceGroupResponse(
            id=result.get("id"),
            name=result["name"],
            description=request.description,
            othername=result["othername"],
        )
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE create child device group failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create ISE child device group: ", exc)


@router.get("/network-device-groups/name/{name}", response_model=ISEDeviceGroupResponse)
async def get_network_device_group_by_name(
    source_id: str,
    name: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISEDeviceGroupResponse:
    group_service = _resolve_group_service(source_id, config)
    try:
        result = await group_service.get_group_by_name(name)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Network device group '{name}' not found",
            )
        group = result["NetworkDeviceGroup"]
        return ISEDeviceGroupResponse(
            id=group.get("id"),
            name=group.get("name", name),
            description=group.get("description"),
            othername=group.get("othername"),
        )
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE get device group by name failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get ISE device group: ", exc)


@router.put(
    "/network-device-groups/{group_id}",
    response_model=ISEDeviceGroupResponse,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def update_network_device_group(
    source_id: str,
    group_id: str,
    request: ISEDeviceGroupUpdateRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISEDeviceGroupResponse:
    group_service = _resolve_group_service(source_id, config)
    try:
        await group_service.update_group(group_id, description=request.description)
        updated = await group_service.get_group(group_id)
        group = updated["NetworkDeviceGroup"]
        return ISEDeviceGroupResponse(
            id=group.get("id"),
            name=group.get("name"),
            description=group.get("description"),
            othername=group.get("othername"),
        )
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE update device group failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update ISE device group: ", exc)


@router.delete(
    "/network-device-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.ise", "delete"))],
)
async def delete_network_device_group(
    source_id: str,
    group_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> None:
    group_service = _resolve_group_service(source_id, config)
    try:
        await group_service.delete_group(group_id)
    except ISENotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger,
            "ISE delete device group failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete ISE device group: ", exc)
