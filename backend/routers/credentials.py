from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.credentials import (
    CredentialCreate,
    CredentialListResponse,
    CredentialPasswordResponse,
    CredentialResponse,
    CredentialUpdate,
)
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNameConflictError,
    CredentialNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/credentials",
    tags=["credentials"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> CredentialsService:
    return CredentialsService(db)


@router.get(
    "",
    response_model=CredentialListResponse,
    dependencies=[Depends(require_permission("credentials", "read"))],
)
async def list_credentials(
    include_expired: bool = Query(False),
    source: str = Query("general"),
    _current_user: User = Depends(get_current_user),
    service: CredentialsService = Depends(_service),
) -> CredentialListResponse:
    credentials = service.list_credentials(include_expired=include_expired, source=source)
    return CredentialListResponse(credentials=credentials)


@router.post(
    "",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("credentials", "write"))],
)
async def create_credential(
    payload: CredentialCreate,
    _current_user: User = Depends(get_current_user),
    service: CredentialsService = Depends(_service),
) -> CredentialResponse:
    try:
        result = service.create_credential(
            name=payload.name,
            username=payload.username,
            cred_type=payload.type,
            password=payload.password,
            valid_until=payload.valid_until.isoformat() if payload.valid_until else None,
            ssh_private_key=payload.ssh_private_key,
            ssh_passphrase=payload.ssh_passphrase,
        )
        return CredentialResponse.model_validate(result)
    except CredentialNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create credential", exc)


@router.put(
    "/{cred_id}",
    response_model=CredentialResponse,
    dependencies=[Depends(require_permission("credentials", "write"))],
)
async def update_credential(
    cred_id: int,
    payload: CredentialUpdate,
    _current_user: User = Depends(get_current_user),
    service: CredentialsService = Depends(_service),
) -> CredentialResponse:
    try:
        result = service.update_credential(
            cred_id,
            name=payload.name,
            username=payload.username,
            cred_type=payload.type,
            password=payload.password,
            valid_until=payload.valid_until.isoformat() if payload.valid_until else None,
            ssh_private_key=payload.ssh_private_key,
            ssh_passphrase=payload.ssh_passphrase,
        )
        return CredentialResponse.model_validate(result)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CredentialNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update credential", exc)


@router.delete(
    "/{cred_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("credentials", "delete"))],
)
async def delete_credential(
    cred_id: int,
    _current_user: User = Depends(get_current_user),
    service: CredentialsService = Depends(_service),
) -> None:
    try:
        service.delete_credential(cred_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete credential", exc)


@router.get(
    "/{cred_id}/password",
    response_model=CredentialPasswordResponse,
    dependencies=[Depends(require_permission("credentials", "reveal"))],
)
async def get_credential_password(
    cred_id: int,
    _current_user: User = Depends(get_current_user),
    service: CredentialsService = Depends(_service),
) -> CredentialPasswordResponse:
    try:
        password = service.get_decrypted_password(cred_id)
        return CredentialPasswordResponse(password=password)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CredentialMissingFieldError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to retrieve credential password", exc)
