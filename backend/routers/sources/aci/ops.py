"""Cisco ACI device preview, per configured source."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_aci_source_config_service
from models.aci import AciDevicePreviewItem, AciDevicePreviewRequest, AciDevicePreviewResponse
from routers.sources.aci.resolve import resolve_saved_credentials
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.device_filters import AciDeviceFilters
from services.aci.source_config_service import AciSourceConfigService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/aci/{source_id}",
    tags=["sources-aci"],
    dependencies=[Depends(require_permission("sources.aci", "read"))],
)


@router.post(
    "/devices/preview",
    response_model=AciDevicePreviewResponse,
    dependencies=[Depends(rate_limited("aci-device-preview", attempts=30, window_seconds=60))],
)
async def preview_devices(
    source_id: str,
    request: AciDevicePreviewRequest,
    _: User = Depends(get_current_user),
    config: AciSourceConfigService = Depends(get_aci_source_config_service),
) -> AciDevicePreviewResponse:
    """The first ``limit`` switches matching the step's filters, and whether more exist."""
    try:
        filters = AciDeviceFilters.from_config(request.filters)
    except AciValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    credentials = resolve_saved_credentials(source_id, config)
    device_service = service_factory.build_aci_device_service(credentials)
    try:
        devices, truncated = await device_service.preview_devices(filters, limit=request.limit)
    except AciValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (AciAPIError, AciAuthError) as exc:
        raise_internal_server_error(
            logger,
            "ACI device preview failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ACI device preview failed: ", exc)

    return AciDevicePreviewResponse(
        devices=[
            AciDevicePreviewItem(
                node_id=device.node_id,
                name=device.name,
                role=device.role,
                pod_id=device.pod_id,
                model=device.model,
                serial_number=device.serial_number,
                software_version=device.software_version,
                fabric_state=device.fabric_state,
                management_ip=device.management_ip,
            )
            for device in devices
        ],
        truncated=truncated,
    )
