"""CRUD for configured Batfish sources (host/port only -- no credential)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_batfish_source_config_service
from models.batfish import (
    BatfishSourceCreateRequest,
    BatfishSourceListResponse,
    BatfishSourceResponse,
    BatfishSourceUpdateRequest,
)
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceConflictError,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "read"))],
)


@router.get("", response_model=BatfishSourceListResponse)
def list_batfish_sources(
    _: User = Depends(get_current_user),
    service: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishSourceListResponse:
    try:
        sources = service.list_sources()
        return BatfishSourceListResponse(
            sources=[BatfishSourceResponse(**s) for s in sources],
            total=len(sources),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Batfish sources: ", exc)


@router.get("/{source_id}", response_model=BatfishSourceResponse)
def get_batfish_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishSourceResponse:
    try:
        return BatfishSourceResponse(**service.get_source(source_id))
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get Batfish source: ", exc)


@router.post(
    "",
    response_model=BatfishSourceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.batfish", "write"))],
)
def create_batfish_source(
    request: BatfishSourceCreateRequest,
    _: User = Depends(get_current_user),
    service: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishSourceResponse:
    try:
        result = service.create_source(
            source_id=request.source_id,
            host=request.host,
            port=request.port,
        )
        return BatfishSourceResponse(**result)
    except BatfishSourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create Batfish source: ", exc)


@router.put(
    "/{source_id}",
    response_model=BatfishSourceResponse,
    dependencies=[Depends(require_permission("sources.batfish", "write"))],
)
def update_batfish_source(
    source_id: str,
    request: BatfishSourceUpdateRequest,
    _: User = Depends(get_current_user),
    service: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishSourceResponse:
    try:
        result = service.update_source(source_id, host=request.host, port=request.port)
        return BatfishSourceResponse(**result)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update Batfish source: ", exc)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.batfish", "delete"))],
)
def delete_batfish_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> None:
    try:
        service.delete_source(source_id)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete Batfish source: ", exc)
