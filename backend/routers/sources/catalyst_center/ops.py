"""Cisco Catalyst Center device preview, per configured source."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_catalyst_center_source_config_service
from models.catalyst_center import (
    CatalystCenterDevicePreviewItem,
    CatalystCenterDevicePreviewRequest,
    CatalystCenterDevicePreviewResponse,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters
from services.catalyst_center.source_config_service import (
    CatalystCenterSourceConfigService,
    CatalystCenterSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/catalyst_center/{source_id}",
    tags=["sources-catalyst-center"],
    dependencies=[Depends(require_permission("sources.catalyst_center", "read"))],
)


def _resolve_credentials(
    source_id: str, config: CatalystCenterSourceConfigService
) -> CatalystCenterCredentials:
    try:
        return config.resolve_credentials(source_id)
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CatalystCenterValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/devices/preview", response_model=CatalystCenterDevicePreviewResponse)
async def preview_devices(
    source_id: str,
    request: CatalystCenterDevicePreviewRequest,
    _: User = Depends(get_current_user),
    config: CatalystCenterSourceConfigService = Depends(get_catalyst_center_source_config_service),
) -> CatalystCenterDevicePreviewResponse:
    """The first ``limit`` devices matching the step's filters, and whether more exist."""
    try:
        filters = CatalystCenterDeviceFilters.from_config(request.filters)
    except CatalystCenterValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    credentials = _resolve_credentials(source_id, config)
    device_service = service_factory.build_catalyst_center_device_service(credentials)
    try:
        devices, truncated = await device_service.preview_devices(filters, limit=request.limit)
    except CatalystCenterValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (CatalystCenterAPIError, CatalystCenterAuthError) as exc:
        raise_internal_server_error(
            logger,
            "Catalyst Center device preview failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Catalyst Center device preview failed: ", exc)

    return CatalystCenterDevicePreviewResponse(
        devices=[
            CatalystCenterDevicePreviewItem(
                id=device.id,
                hostname=device.hostname,
                management_ip=device.management_ip,
                family=device.family,
                role=device.role,
                software_type=device.software_type,
                software_version=device.software_version,
                platform_id=device.platform_id,
                reachability_status=device.reachability_status,
            )
            for device in devices
        ],
        truncated=truncated,
    )
