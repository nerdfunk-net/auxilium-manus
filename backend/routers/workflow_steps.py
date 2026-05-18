from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from core.auth import get_current_user
from models.plugins import (
    DevicePreview,
    DeviceSelectionPreviewRequest,
    DeviceSelectionPreviewResponse,
    FieldOption,
    FieldOptionsResponse,
    FieldValuesRequest,
    FieldValuesResponse,
    PluginDefinition,
    PluginListResponse,
    PluginRegistryResponse,
)
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.device_selection.models import (
    LogicalCondition,
    LogicalOperation,
)
from workflow_steps.device_selection.nautobot.evaluator import NautobotEvaluator
from workflow_steps.device_selection.nautobot.query_service import NautobotQueryService

_WORKFLOW_STEPS_ROOT = Path(__file__).resolve().parent.parent / "workflow_steps"

_FIELD_OPTIONS = [
    FieldOption(value="name", label="Device Name"),
    FieldOption(value="location", label="Location"),
    FieldOption(value="role", label="Role"),
    FieldOption(value="status", label="Status"),
    FieldOption(value="tag", label="Tag"),
    FieldOption(value="device_type", label="Device Type"),
    FieldOption(value="manufacturer", label="Manufacturer"),
    FieldOption(value="platform", label="Platform"),
    FieldOption(value="has_primary", label="Has Primary IP"),
    FieldOption(value="ip_prefix", label="IP Prefix"),
]

_OPERATOR_OPTIONS = [
    FieldOption(value="equals", label="Equals"),
    FieldOption(value="not_equals", label="Not Equals"),
    FieldOption(value="contains", label="Contains"),
    FieldOption(value="not_contains", label="Not Contains"),
]

# Fields that support the ip_prefix operator for prefix-based matching
_IP_PREFIX_OPERATOR_OPTIONS = [
    FieldOption(value="within_include", label="Within (include)"),
    FieldOption(value="within", label="Within"),
    FieldOption(value="exact", label="Exact"),
]


class PluginConfigResponse(BaseModel):
    plugin_id: str
    config: dict[str, Any]


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps",
    tags=["workflow-steps"],
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


@router.get("/device-selection/field-options", response_model=FieldOptionsResponse)
async def get_field_options(
    _: dict = Depends(get_current_user),
) -> FieldOptionsResponse:
    """Return static list of filterable fields and operators. No Nautobot call needed."""
    return FieldOptionsResponse(fields=_FIELD_OPTIONS, operators=_OPERATOR_OPTIONS)


@router.post("/device-selection/field-values", response_model=FieldValuesResponse)
async def get_field_values(
    body: FieldValuesRequest,
    _: dict = Depends(get_current_user),
) -> FieldValuesResponse:
    """Return distinct values for the given field by querying Nautobot."""
    qs = NautobotQueryService(body.nautobot_url, body.nautobot_token)
    try:
        values = await qs.get_field_values(body.field)
    except Exception as exc:
        logger.exception("Failed to fetch field values for '%s'", body.field)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach Nautobot. Check URL and token.",
        ) from exc

    if body.field in {"name", "ip_prefix"}:
        input_type = "text"
    elif body.field == "has_primary":
        input_type = "boolean"
    else:
        input_type = "select"
    return FieldValuesResponse(field=body.field, values=values, input_type=input_type)


@router.post("/device-selection/preview", response_model=DeviceSelectionPreviewResponse)
async def preview_device_selection_endpoint(
    body: DeviceSelectionPreviewRequest,
    _: dict = Depends(get_current_user),
) -> DeviceSelectionPreviewResponse:
    """Query Nautobot for devices matching the provided filter tree."""
    qs = NautobotQueryService(body.nautobot_url, body.nautobot_token)
    evaluator = NautobotEvaluator(qs)

    operations = [
        LogicalOperation(
            operation_type=op.operation_type,
            conditions=[
                LogicalCondition(field=c.field, operator=c.operator, value=c.value)
                for c in op.conditions
            ],
            nested_operations=_convert_nested(op.nested_operations),
        )
        for op in body.operations
    ]

    try:
        devices = await evaluator.evaluate(operations)
    except Exception as exc:
        logger.exception("Device selection preview failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach Nautobot. Check URL and token.",
        ) from exc

    previews = [DevicePreview(**d.model_dump()) for d in devices]
    return DeviceSelectionPreviewResponse(devices=previews, total=len(previews))


def _convert_nested(nested_ops: list) -> list[LogicalOperation]:
    result = []
    for op in nested_ops:
        result.append(LogicalOperation(
            operation_type=op.operation_type,
            conditions=[
                LogicalCondition(field=c.field, operator=c.operator, value=c.value)
                for c in op.conditions
            ],
            nested_operations=_convert_nested(op.nested_operations),
        ))
    return result


@router.get("/{plugin_id}/get-config", response_model=PluginConfigResponse)
async def get_plugin_config(
    plugin_id: str,
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    plugin = service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")

    config_module_path = _WORKFLOW_STEPS_ROOT / plugin.directory / "config.py"
    if not config_module_path.is_file():
        return PluginConfigResponse(plugin_id=plugin_id, config={})

    module_name = f"workflow_steps.{plugin.directory}.config"
    spec = importlib.util.spec_from_file_location(module_name, config_module_path)
    if spec is None or spec.loader is None:
        logger.warning("Cannot load config module for plugin '%s'", plugin_id)
        return PluginConfigResponse(plugin_id=plugin_id, config={})

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    get_config = getattr(module, "get_config", None)
    if not callable(get_config):
        return PluginConfigResponse(plugin_id=plugin_id, config={})

    try:
        cfg = get_config()
    except Exception:
        logger.exception("get_config() failed for plugin '%s'", plugin_id)
        return PluginConfigResponse(plugin_id=plugin_id, config={})

    return PluginConfigResponse(plugin_id=plugin_id, config=cfg)


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
