"""CRUD for configured Mattermost sources (connection settings + credential)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_mattermost_source_config_service
from models.mattermost import (
    MattermostSourceCreateRequest,
    MattermostSourceListResponse,
    MattermostSourceResponse,
    MattermostSourceUpdateRequest,
)
from services.mattermost.source_config_service import (
    MattermostSourceConfigService,
    MattermostSourceConflictError,
    MattermostSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/mattermost",
    tags=["sources-mattermost"],
    dependencies=[Depends(require_permission("sources.mattermost", "read"))],
)


@router.get("", response_model=MattermostSourceListResponse)
def list_mattermost_sources(
    _: User = Depends(get_current_user),
    service: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> MattermostSourceListResponse:
    try:
        sources = service.list_sources()
        return MattermostSourceListResponse(
            sources=[MattermostSourceResponse(**s) for s in sources],
            total=len(sources),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Mattermost sources: ", exc)


@router.get("/{source_id}", response_model=MattermostSourceResponse)
def get_mattermost_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> MattermostSourceResponse:
    try:
        return MattermostSourceResponse(**service.get_source(source_id))
    except MattermostSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get Mattermost source: ", exc)


@router.post(
    "",
    response_model=MattermostSourceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.mattermost", "write"))],
)
def create_mattermost_source(
    request: MattermostSourceCreateRequest,
    _: User = Depends(get_current_user),
    service: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> MattermostSourceResponse:
    try:
        result = service.create_source(
            source_id=request.source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return MattermostSourceResponse(**result)
    except MattermostSourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create Mattermost source: ", exc)


@router.put(
    "/{source_id}",
    response_model=MattermostSourceResponse,
    dependencies=[Depends(require_permission("sources.mattermost", "write"))],
)
def update_mattermost_source(
    source_id: str,
    request: MattermostSourceUpdateRequest,
    _: User = Depends(get_current_user),
    service: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> MattermostSourceResponse:
    try:
        result = service.update_source(
            source_id,
            url=request.url,
            credential_id=request.credential_id,
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
        return MattermostSourceResponse(**result)
    except MattermostSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update Mattermost source: ", exc)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.mattermost", "delete"))],
)
def delete_mattermost_source(
    source_id: str,
    _: User = Depends(get_current_user),
    service: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> None:
    try:
        service.delete_source(source_id)
    except MattermostSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete Mattermost source: ", exc)
