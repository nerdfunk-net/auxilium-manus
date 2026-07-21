from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.netmiko import (
    NetmikoCommandEntry,
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
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.cisco_config_parsing import (
    parse_cisco_config_text,
    platform_hint_for_network_driver,
)

logger = logging.getLogger(__name__)

# Synthetic node id for editor preview entries, mirroring a workflow step node.
EDITOR_NODE_ID = "template-editor"

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


def _parse_output(raw: str, *, use_textfsm: bool) -> Any:
    """Mirror the render-jinja-template step: parsed is only set with TextFSM."""
    if not use_textfsm:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@router.post("/run-commands", response_model=NetmikoRunCommandsResponse)
async def run_commands(
    payload: NetmikoRunCommandsRequest,
    _current_user: User = Depends(get_current_user),
    credentials_service: CredentialsService = Depends(_credentials_service),
) -> NetmikoRunCommandsResponse:
    commands = [command.strip() for command in payload.commands if command.strip()]
    if not commands:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one non-empty command is required",
        )

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
        result = await netmiko.send_commands(
            host=payload.host,
            network_driver=payload.network_driver,
            platform=payload.platform,
            username=credential["username"],
            password=password,
            commands=commands,
            use_textfsm=payload.use_textfsm,
        )
    except NetmikoConnectionError as exc:
        # Device-side connect/auth/timeout failure: report gracefully so the
        # editor can surface it, rather than emitting a generic 500.
        logger.info("Netmiko preview connection failed host=%s", payload.host)
        return NetmikoRunCommandsResponse(success=False, commands=[], error=str(exc))

    try:
        entries = [
            NetmikoCommandEntry(
                node_id=EDITOR_NODE_ID,
                name=command,
                success=result.success,
                raw=result.command_outputs.get(command, ""),
                parsed=_parse_output(
                    result.command_outputs.get(command, ""),
                    use_textfsm=payload.use_textfsm,
                ),
            )
            for command in commands
        ]
        return NetmikoRunCommandsResponse(
            success=result.success,
            commands=entries,
            error=result.error,
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to execute Netmiko commands", exc)


@router.post("/get-configs", response_model=NetmikoGetConfigsResponse)
async def get_configs(
    payload: NetmikoGetConfigsRequest,
    _current_user: User = Depends(get_current_user),
    credentials_service: CredentialsService = Depends(_credentials_service),
) -> NetmikoGetConfigsResponse:
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
        result = await netmiko.get_configs(
            host=payload.host,
            network_driver=payload.network_driver,
            platform=payload.platform,
            username=credential["username"],
            password=password,
            include_running=True,
            include_startup=True,
        )
    except NetmikoConnectionError as exc:
        logger.info("Netmiko get-configs connection failed host=%s", payload.host)
        return NetmikoGetConfigsResponse(success=False, error=str(exc))

    if not result.success:
        return NetmikoGetConfigsResponse(success=False, error=result.error)

    try:
        platform_hint = platform_hint_for_network_driver(payload.network_driver)
        parsed = {
            "running": parse_cisco_config_text(result.running_config, platform_hint)
            if result.running_config is not None
            else None,
            "startup": parse_cisco_config_text(result.startup_config, platform_hint)
            if result.startup_config is not None
            else None,
        }
        return NetmikoGetConfigsResponse(success=True, parsed=parsed)
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to parse device configuration", exc)
