from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.domain_exceptions import DomainError
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.netmiko import (
    NetmikoGetConfigsRequest,
    NetmikoGetConfigsResponse,
    NetmikoRunCommandsRequest,
    NetmikoRunCommandsResponse,
)
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
)
from services.network.netmiko.connection import NetmikoConnectionError
from services.network.netmiko.preview_service import NetmikoPreviewService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/netmiko",
    tags=["netmiko"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("netmiko", "execute")),
    ],
)


def _credentials_service(db: Session = Depends(get_db)) -> CredentialsService:
    return CredentialsService(db)


def _preview_service(
    credentials_service: CredentialsService = Depends(_credentials_service),
) -> NetmikoPreviewService:
    return NetmikoPreviewService(credentials_service)


@router.post("/run-commands", response_model=NetmikoRunCommandsResponse)
async def run_commands(
    payload: NetmikoRunCommandsRequest,
    current_user: User = Depends(get_current_user),
    service: NetmikoPreviewService = Depends(_preview_service),
) -> NetmikoRunCommandsResponse:
    try:
        return await service.run_commands(payload, acting_user_id=current_user.id)
    except DomainError:
        raise
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NetmikoConnectionError as exc:
        logger.info("Netmiko preview connection failed")
        return NetmikoRunCommandsResponse(success=False, commands=[], error=str(exc))
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to execute Netmiko commands", exc)


@router.post("/get-configs", response_model=NetmikoGetConfigsResponse)
async def get_configs(
    payload: NetmikoGetConfigsRequest,
    current_user: User = Depends(get_current_user),
    service: NetmikoPreviewService = Depends(_preview_service),
) -> NetmikoGetConfigsResponse:
    try:
        return await service.get_configs(payload, acting_user_id=current_user.id)
    except DomainError:
        raise
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NetmikoConnectionError as exc:
        logger.info("Netmiko get-configs connection failed")
        return NetmikoGetConfigsResponse(success=False, error=str(exc))
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to parse device configuration", exc)
