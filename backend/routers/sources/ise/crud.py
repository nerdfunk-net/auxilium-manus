"""CRUD for configured Cisco ISE sources (connection settings + credential)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_ise_source_config_service
from models.ise import (
    ISESourceCreateRequest,
    ISESourceListResponse,
    ISESourceResponse,
    ISESourceUpdateRequest,
)
from services.credentials.exceptions import CredentialNameConflictError
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
            username=request.username,
            password=request.password,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return ISESourceResponse(**result)
    except (ISESourceConflictError, CredentialNameConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
            username=request.username,
            password=request.password,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return ISESourceResponse(**result)
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
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
