"""CRUD for configured Cisco ISE sources (connection settings + credential)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_ise_source_config_service
from models.ise import (
    ISESourceCreateRequest,
    ISESourceListResponse,
    ISESourceResponse,
    ISESourceUpdateRequest,
    ISETestConnectionRequest,
    ISETestConnectionResponse,
)
from services.credentials.source_credentials import SourceCredentialError
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from services.ise.credentials import ISECredentials
from services.ise.source_config_service import (
    ISESourceConfigService,
    ISESourceConflictError,
    ISESourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/ise",
    tags=["sources-ise"],
    dependencies=[Depends(require_permission("sources.ise", "read"))],
)


@router.get("", response_model=ISESourceListResponse)
async def list_ise_sources(
    _: User = Depends(get_current_user),
    service: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISESourceListResponse:
    try:
        sources = service.list_sources()
        return ISESourceListResponse(
            sources=[ISESourceResponse(**s) for s in sources],
            total=len(sources),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list ISE sources: ", exc)


@router.get("/{source_id}", response_model=ISESourceResponse)
async def get_ise_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISESourceResponse:
    try:
        return ISESourceResponse(**service.get_source(source_id))
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get ISE source: ", exc)


@router.post(
    "",
    response_model=ISESourceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def create_ise_source(
    request: ISESourceCreateRequest,
    _: User = Depends(get_current_user),
    service: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISESourceResponse:
    try:
        result = service.create_source(
            source_id=request.source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return ISESourceResponse(**result)
    except ISESourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create ISE source: ", exc)


@router.put(
    "/{source_id}",
    response_model=ISESourceResponse,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def update_ise_source(
    source_id: str,
    request: ISESourceUpdateRequest,
    _: User = Depends(get_current_user),
    service: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISESourceResponse:
    try:
        result = service.update_source(
            source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return ISESourceResponse(**result)
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ISEValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update ISE source: ", exc)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.ise", "delete"))],
)
async def delete_ise_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> None:
    try:
        service.delete_source(source_id)
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete ISE source: ", exc)


def _resolve_test_credentials(
    request: ISETestConnectionRequest,
    config: ISESourceConfigService,
) -> ISECredentials:
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ISEValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=ISETestConnectionResponse,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def test_connection(
    request: ISETestConnectionRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISETestConnectionResponse:
    """Test ISE connectivity using a saved ``source_id`` or inline dialog values."""
    credentials = _resolve_test_credentials(request, config)
    device_service = service_factory.build_ise_network_device_service(credentials)
    try:
        await device_service.test_connection()
        return ISETestConnectionResponse(success=True, message="Connection successful")
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("ISE test connection failed (error_id=%s): %s", error_id, exc)
        return ISETestConnectionResponse(
            success=False,
            message=(
                f"Connection failed (ref: {error_id}). "
                "Check the source configuration and network reachability."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ISE test connection failed: ", exc)
