"""Async Netmiko orchestration for workflow steps, backed by a DeviceSessionPool.

Every public method leaves the session in privileged-exec base state (config
mode always exited, no pending interactive prompts) before returning, so a
pooled session is always safe for a later step to reuse — see
doc/DURABLE_SSH_SESSION.md §3.4.
"""

from __future__ import annotations

import logging

from services.network.netmiko.connection import (
    DEFAULT_READ_TIMEOUT,
    CommandResult,
    ConfigResult,
    DeployResult,
    NetmikoConnectionError,
    NetmikoDeviceSession,
)
from services.network.netmiko.platform import resolve_netmiko_device_type
from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


class NetmikoService:
    """Run Netmiko operations against a run-segment-scoped DeviceSessionPool."""

    def __init__(self, *, pool: DeviceSessionPool) -> None:
        self._pool = pool

    async def send_command(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        command: str,
        credential_reference: str,
        privileged: bool = True,
    ) -> CommandResult:
        return await self.send_commands(
            host=host,
            network_driver=network_driver,
            platform=platform,
            username=username,
            password=password,
            commands=[command],
            credential_reference=credential_reference,
            privileged=privileged,
        )

    async def send_commands(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        commands: list[str],
        credential_reference: str,
        privileged: bool = True,
        use_textfsm: bool = False,
        device_type: str | None = None,
    ) -> CommandResult:
        del privileged  # pooled sessions always connect privileged; see module docstring
        resolved_device_type = device_type or resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )

        def _op(session: NetmikoDeviceSession) -> CommandResult:
            return session.send_commands(commands, use_textfsm=use_textfsm)

        return await self._pool.run_on_device(
            host=host,
            device_type=resolved_device_type,
            credential_reference=credential_reference,
            username=username,
            password=password,
            op=_op,
        )

    async def deploy_config(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        commands: list[str],
        mode: str,
        write_config: bool,
        credential_reference: str,
        device_type: str | None = None,
        read_timeout: int | None = None,
        auto_confirm_prompts: bool = False,
    ) -> DeployResult:
        resolved_device_type = device_type or resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )

        def _op(session: NetmikoDeviceSession) -> DeployResult:
            result = session.deploy_config(
                commands,
                mode=mode,
                read_timeout=read_timeout or DEFAULT_READ_TIMEOUT,
                auto_confirm_prompts=auto_confirm_prompts,
            )
            if not result.success or not write_config:
                return result
            try:
                save_output = session.save_running_config()
                return DeployResult(
                    success=True,
                    config_output=result.config_output,
                    save_output=save_output,
                )
            except NetmikoConnectionError as exc:
                return DeployResult(
                    success=False, config_output=result.config_output, error=str(exc)
                )

        return await self._pool.run_on_device(
            host=host,
            device_type=resolved_device_type,
            credential_reference=credential_reference,
            username=username,
            password=password,
            op=_op,
        )

    async def get_running_config(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        credential_reference: str,
    ) -> str:
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )

        def _op(session: NetmikoDeviceSession) -> str:
            return session.get_running_config()

        return await self._pool.run_on_device(
            host=host,
            device_type=device_type,
            credential_reference=credential_reference,
            username=username,
            password=password,
            op=_op,
        )

    async def get_startup_config(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        credential_reference: str,
    ) -> str:
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )

        def _op(session: NetmikoDeviceSession) -> str:
            return session.get_startup_config()

        return await self._pool.run_on_device(
            host=host,
            device_type=device_type,
            credential_reference=credential_reference,
            username=username,
            password=password,
            op=_op,
        )

    async def get_configs(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        credential_reference: str,
        include_running: bool = True,
        include_startup: bool = True,
    ) -> ConfigResult:
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )

        def _op(session: NetmikoDeviceSession) -> ConfigResult:
            running: str | None = None
            startup: str | None = None
            try:
                if include_running:
                    running = session.get_running_config()
                if include_startup:
                    startup = session.get_startup_config()
                return ConfigResult(
                    success=True,
                    running_config=running,
                    startup_config=startup,
                )
            except NetmikoConnectionError as exc:
                return ConfigResult(success=False, error=str(exc))
            except Exception as exc:
                return ConfigResult(success=False, error=str(exc))

        return await self._pool.run_on_device(
            host=host,
            device_type=device_type,
            credential_reference=credential_reference,
            username=username,
            password=password,
            op=_op,
        )
