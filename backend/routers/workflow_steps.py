from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.auth import get_current_user, require_permission
from models.plugins import (
    PluginConfigResponse,
    PluginDefinition,
    PluginListResponse,
    PluginRegistryResponse,
)
from services.plugin_registry.plugin_registry_service import PluginRegistryService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
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
    include_disabled: bool = Query(default=False),
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginListResponse:
    return PluginListResponse(plugins=service.list_plugins(include_disabled=include_disabled))


@router.get("/registry", response_model=PluginRegistryResponse)
async def get_plugin_registry(
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginRegistryResponse:
    registry = service.get_registry()
    return PluginRegistryResponse(schema_version=registry.schema_version, plugins=registry.plugins)


@router.get("/{plugin_id}/get-config", response_model=PluginConfigResponse)
async def get_plugin_config(
    plugin_id: str,
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    plugin = service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    cfg = service.get_plugin_config(plugin_id)
    return PluginConfigResponse(plugin_id=plugin_id, config=cfg or {})


@router.get("/{plugin_id}", response_model=PluginDefinition)
async def get_plugin(
    plugin_id: str,
    include_disabled: bool = Query(default=False),
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginDefinition:
    plugin = service.get_plugin(plugin_id, include_disabled=include_disabled)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return plugin
