"""CRUD + test-connection for configured Cisco Catalyst Center sources."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_catalyst_center_source_config_service
from models.catalyst_center import (
    CatalystCenterSourceCreateRequest,
    CatalystCenterSourceListResponse,
    CatalystCenterSourceResponse,
    CatalystCenterSourceUpdateRequest,
    CatalystCenterTestConnectionRequest,
    CatalystCenterTestConnectionResponse,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.source_config_service import (
    CatalystCenterSourceConfigService,
    CatalystCenterSourceConflictError,
    CatalystCenterSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/catalyst_center",
    tags=["sources-catalyst-center"],
    dependencies=[Depends(require_permission("sources.catalyst_center", "read"))],
)

_ConfigService = Depends(get_catalyst_center_source_config_service)


@router.get("", response_model=CatalystCenterSourceListResponse)
async def list_catalyst_center_sources(
    _: User = Depends(get_current_user),
    service: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterSourceListResponse:
    try:
        sources = service.list_sources()
        return CatalystCenterSourceListResponse(
            sources=[CatalystCenterSourceResponse(**s) for s in sources],
            total=len(sources),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Catalyst Center sources: ", exc)


@router.get("/{source_id}", response_model=CatalystCenterSourceResponse)
async def get_catalyst_center_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterSourceResponse:
    try:
        return CatalystCenterSourceResponse(**service.get_source(source_id))
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get Catalyst Center source: ", exc)


@router.post(
    "",
    response_model=CatalystCenterSourceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.catalyst_center", "write"))],
)
async def create_catalyst_center_source(
    request: CatalystCenterSourceCreateRequest,
    _: User = Depends(get_current_user),
    service: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterSourceResponse:
    try:
        result = service.create_source(
            source_id=request.source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return CatalystCenterSourceResponse(**result)
    except CatalystCenterSourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (CatalystCenterValidationError, UnsafeURLError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create Catalyst Center source: ", exc)


@router.put(
    "/{source_id}",
    response_model=CatalystCenterSourceResponse,
    dependencies=[Depends(require_permission("sources.catalyst_center", "write"))],
)
async def update_catalyst_center_source(
    source_id: str,
    request: CatalystCenterSourceUpdateRequest,
    _: User = Depends(get_current_user),
    service: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterSourceResponse:
    try:
        result = service.update_source(
            source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return CatalystCenterSourceResponse(**result)
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CatalystCenterValidationError, UnsafeURLError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update Catalyst Center source: ", exc)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.catalyst_center", "delete"))],
)
async def delete_catalyst_center_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: CatalystCenterSourceConfigService = _ConfigService,
) -> None:
    try:
        service.delete_source(source_id)
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete Catalyst Center source: ", exc)


def _resolve_test_credentials(
    request: CatalystCenterTestConnectionRequest,
    config: CatalystCenterSourceConfigService,
) -> CatalystCenterCredentials:
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CatalystCenterValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=CatalystCenterTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.catalyst_center", "write"))],
)
async def test_connection(
    request: CatalystCenterTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterTestConnectionResponse:
    """Test connectivity using a saved ``source_id`` or inline dialog values."""
    credentials = _resolve_test_credentials(request, config)
    device_service = service_factory.build_catalyst_center_device_service(credentials)
    try:
        version = await device_service.test_connection()
        return CatalystCenterTestConnectionResponse(
            success=True, message="Connection successful", release=version
        )
    except CatalystCenterValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (CatalystCenterAuthError, CatalystCenterAPIError) as exc:
        error_id = uuid.uuid4()
        logger.warning("Catalyst Center test connection failed (error_id=%s): %s", error_id, exc)
        return CatalystCenterTestConnectionResponse(
            success=False,
            message=(
                f"Connection failed (ref: {error_id}). "
                "Check the credentials, URL and network reachability."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Catalyst Center test connection failed: ", exc)
