"""Netmiko editor-preview operations — run-commands and get-configs.

Moved out of routers/netmiko.py so the router stays a thin HTTP shim
(doc/refactoring/GROK_46.md H5b). Business logic and domain-error mapping
live here; the router only translates domain errors and a handful of
typed credential/connection exceptions to HTTP responses.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.config import settings
from core.domain_exceptions import NotFoundError, ValidationFailedError
from core.safe_hosts import validate_netmiko_preview_host
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
from services.network.cisco_config_parsing import (
    parse_cisco_config_text,
    platform_hint_for_network_driver,
)
from services.network.netmiko.connection import NetmikoConnectionError
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

# Synthetic node id for editor preview entries, mirroring a workflow step node.
EDITOR_NODE_ID = "template-editor"


def _parse_output(raw: str, *, use_textfsm: bool) -> Any:
    """Mirror the render-jinja-template step: parsed is only set with TextFSM."""
    if not use_textfsm:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class NetmikoPreviewService:
    def __init__(self, credentials_service: CredentialsService) -> None:
        self._credentials = credentials_service

    def _resolve_host(self, host: str) -> str:
        try:
            return validate_netmiko_preview_host(
                host,
                environment=settings.environment,
                allow_arbitrary=settings.allow_netmiko_arbitrary_hosts,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc

    def _resolve_ssh_credential(
        self, credential_id: int, *, acting_user_id: int
    ) -> tuple[dict[str, Any], str]:
        credential = self._credentials.get_credential_by_id(
            credential_id, acting_user_id=acting_user_id
        )
        if credential is None:
            raise NotFoundError(f"Credential {credential_id} not found")
        if credential["type"] != "ssh":
            raise ValidationFailedError("Selected credential must be an SSH credential")

        try:
            password = self._credentials.get_decrypted_password(
                credential_id, acting_user_id=acting_user_id
            )
        except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
            raise ValidationFailedError(str(exc)) from exc

        return credential, password

    async def run_commands(
        self, payload: NetmikoRunCommandsRequest, *, acting_user_id: int
    ) -> NetmikoRunCommandsResponse:
        commands = [command.strip() for command in payload.commands if command.strip()]
        if not commands:
            raise ValidationFailedError("At least one non-empty command is required")

        host = self._resolve_host(payload.host)
        credential, password = self._resolve_ssh_credential(
            payload.credential_id, acting_user_id=acting_user_id
        )

        pool = DeviceSessionPool(max_workers=1, enabled=False)
        try:
            netmiko = NetmikoService(pool=pool)
            result = await netmiko.send_commands(
                host=host,
                network_driver=payload.network_driver,
                platform=payload.platform,
                username=credential["username"],
                password=password,
                commands=commands,
                use_textfsm=payload.use_textfsm,
                credential_reference=f"credential:{payload.credential_id}",
            )
        except NetmikoConnectionError as exc:
            # Device-side connect/auth/timeout failure: report gracefully so the
            # editor can surface it, rather than emitting a generic 500.
            logger.info("Netmiko preview connection failed host=%s", host)
            return NetmikoRunCommandsResponse(success=False, commands=[], error=str(exc))
        finally:
            await pool.close()

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

    async def get_configs(
        self, payload: NetmikoGetConfigsRequest, *, acting_user_id: int
    ) -> NetmikoGetConfigsResponse:
        host = self._resolve_host(payload.host)
        credential, password = self._resolve_ssh_credential(
            payload.credential_id, acting_user_id=acting_user_id
        )

        pool = DeviceSessionPool(max_workers=1, enabled=False)
        try:
            netmiko = NetmikoService(pool=pool)
            result = await netmiko.get_configs(
                host=host,
                network_driver=payload.network_driver,
                platform=payload.platform,
                username=credential["username"],
                password=password,
                include_running=True,
                include_startup=True,
                credential_reference=f"credential:{payload.credential_id}",
            )
        except NetmikoConnectionError as exc:
            logger.info("Netmiko get-configs connection failed host=%s", host)
            return NetmikoGetConfigsResponse(success=False, error=str(exc))
        finally:
            await pool.close()

        if not result.success:
            return NetmikoGetConfigsResponse(success=False, error=result.error)

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
