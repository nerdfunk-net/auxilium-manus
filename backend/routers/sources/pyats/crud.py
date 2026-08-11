"""CRUD for configured pyATS shim sources (connection settings + credential)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_pyats_source_config_service
from models.pyats import (
    PyATSSourceCreateRequest,
    PyATSSourceListResponse,
    PyATSSourceResponse,
    PyATSSourceUpdateRequest,
)
from services.credentials.exceptions import CredentialNameConflictError
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceConflictError,
    PyATSSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/pyats",
    tags=["sources-pyats"],
    dependencies=[Depends(require_permission("sources.pyats", "read"))],
)


@router.get("", response_model=PyATSSourceListResponse)
async def list_pyats_sources(
    _: User = Depends(get_current_user),
    service: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> PyATSSourceListResponse:
    try:
        sources = service.list_sources()
        return PyATSSourceListResponse(
            sources=[PyATSSourceResponse(**s) for s in sources],
            total=len(sources),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list pyATS sources: ", exc)


@router.get("/{source_id}", response_model=PyATSSourceResponse)
async def get_pyats_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> PyATSSourceResponse:
    try:
        return PyATSSourceResponse(**service.get_source(source_id))
    except PyATSSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get pyATS source: ", exc)


@router.post(
    "",
    response_model=PyATSSourceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.pyats", "write"))],
)
async def create_pyats_source(
    request: PyATSSourceCreateRequest,
    _: User = Depends(get_current_user),
    service: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> PyATSSourceResponse:
    try:
        result = service.create_source(
            source_id=request.source_id,
            url=request.url,
            token=request.token,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return PyATSSourceResponse(**result)
    except (PyATSSourceConflictError, CredentialNameConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create pyATS source: ", exc)


@router.put(
    "/{source_id}",
    response_model=PyATSSourceResponse,
    dependencies=[Depends(require_permission("sources.pyats", "write"))],
)
async def update_pyats_source(
    source_id: str,
    request: PyATSSourceUpdateRequest,
    _: User = Depends(get_current_user),
    service: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> PyATSSourceResponse:
    try:
        result = service.update_source(
            source_id,
            url=request.url,
            token=request.token,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return PyATSSourceResponse(**result)
    except PyATSSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update pyATS source: ", exc)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.pyats", "delete"))],
)
async def delete_pyats_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> None:
    try:
        service.delete_source(source_id)
    except PyATSSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete pyATS source: ", exc)
