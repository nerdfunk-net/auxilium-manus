from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.netmiko import NetmikoRunCommandRequest, NetmikoRunCommandResponse
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
)
from services.network.netmiko.service import NetmikoService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/netmiko",
    tags=["netmiko"],
    dependencies=[Depends(get_current_user)],
)


def _credentials_service(db: Session = Depends(get_db)) -> CredentialsService:
    return CredentialsService(db)


@router.post("/run-command", response_model=NetmikoRunCommandResponse)
async def run_command(
    payload: NetmikoRunCommandRequest,
    _current_user: User = Depends(get_current_user),
    credentials_service: CredentialsService = Depends(_credentials_service),
) -> NetmikoRunCommandResponse:
    credential = credentials_service.get_credential_by_id(payload.credential_id)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {payload.credential_id} not found",
        )
    if credential["type"] != "ssh":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected credential must be an SSH credential",
        )

    try:
        password = credentials_service.get_decrypted_password(payload.credential_id)
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        netmiko = NetmikoService()
        result = await netmiko.run_command_dual(
            host=payload.host,
            network_driver=payload.network_driver,
            platform=payload.platform,
            username=credential["username"],
            password=password,
            command=payload.command,
        )
        return NetmikoRunCommandResponse(
            success=result.success,
            raw_output=result.raw_output,
            parsed_output=result.parsed_output,
            error=result.error,
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to execute Netmiko command", exc)
