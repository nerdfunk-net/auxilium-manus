from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.auth import get_current_user
from models.plugins import (
    DeviceSelectionPreviewRequest,
    DeviceSelectionPreviewResponse,
    DevicePreview,
    PluginDefinition,
    PluginListResponse,
    PluginRegistryResponse,
)
from workflow_steps.device_selection.preview import (
    NautobotNotConfiguredError,
    preview_device_selection,
)
from services.plugin_registry.plugin_registry_service import PluginRegistryService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/plugins",
    tags=["plugins"],
    dependencies=[Depends(get_current_user)],
)


def get_plugin_service(request: Request) -> PluginRegistryService:
    service = getattr(request.app.state, "plugin_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin registry unavailable",
        )

    return service


@router.get("", response_model=PluginListResponse)
async def list_plugins(
    include_disabled: bool = Query(
        default=False,
        description="Include disabled plugins from the startup registry.",
    ),
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginListResponse:
    return PluginListResponse(plugins=service.list_plugins(include_disabled=include_disabled))


@router.get("/registry", response_model=PluginRegistryResponse)
async def get_plugin_registry(
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginRegistryResponse:
    registry = service.get_registry()

    return PluginRegistryResponse(
        schema_version=registry.schema_version,
        plugins=registry.plugins,
    )


@router.get("/{plugin_id}", response_model=PluginDefinition)
async def get_plugin(
    plugin_id: str,
    include_disabled: bool = Query(
        default=False,
        description="Allow lookup of disabled plugins by id.",
    ),
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginDefinition:
    plugin = service.get_plugin(plugin_id, include_disabled=include_disabled)

    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plugin not found",
        )

    return plugin


@router.post("/device-selection/preview", response_model=DeviceSelectionPreviewResponse)
async def preview_device_selection_endpoint(
    body: DeviceSelectionPreviewRequest,
    _: dict = Depends(get_current_user),
) -> DeviceSelectionPreviewResponse:
    """Query Nautobot for devices matching the provided filter.

    Requires NAUTOBOT_URL and NAUTOBOT_TOKEN environment variables.
    """
    try:
        devices = await preview_device_selection(device_filter=body.device_filter)
        previews = [DevicePreview(**d) for d in devices]
        return DeviceSelectionPreviewResponse(devices=previews, total=len(previews))
    except NautobotNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception("Device selection preview failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach Nautobot. Check NAUTOBOT_URL and NAUTOBOT_TOKEN.",
        )
