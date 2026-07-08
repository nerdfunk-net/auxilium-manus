"""Async Netmiko orchestration for workflow steps."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from services.network.netmiko.connection import (
    CommandResult,
    ConfigResult,
    NetmikoConnectionError,
    NetmikoDeviceSession,
)
from services.network.netmiko.platform import resolve_netmiko_device_type

logger = logging.getLogger(__name__)


class NetmikoService:
    """Run blocking Netmiko operations on a shared thread pool."""

    def __init__(self, *, max_workers: int = 10) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    async def send_command(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        command: str,
        privileged: bool = True,
    ) -> CommandResult:
        return await self.send_commands(
            host=host,
            network_driver=network_driver,
            platform=platform,
            username=username,
            password=password,
            commands=[command],
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
        privileged: bool = True,
        use_textfsm: bool = False,
        device_type: str | None = None,
    ) -> CommandResult:
        loop = asyncio.get_running_loop()
        resolved_device_type = device_type or resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )
        return await loop.run_in_executor(
            self._executor,
            _sync_send_commands,
            host,
            resolved_device_type,
            username,
            password,
            commands,
            privileged,
            use_textfsm,
        )

    async def get_running_config(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
    ) -> str:
        loop = asyncio.get_running_loop()
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )
        return await loop.run_in_executor(
            self._executor,
            _sync_get_running_config,
            host,
            device_type,
            username,
            password,
        )

    async def get_startup_config(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
    ) -> str:
        loop = asyncio.get_running_loop()
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )
        return await loop.run_in_executor(
            self._executor,
            _sync_get_startup_config,
            host,
            device_type,
            username,
            password,
        )

    async def get_configs(
        self,
        *,
        host: str,
        network_driver: str | None,
        platform: str | None,
        username: str,
        password: str,
        include_running: bool = True,
        include_startup: bool = True,
    ) -> ConfigResult:
        loop = asyncio.get_running_loop()
        device_type = resolve_netmiko_device_type(
            network_driver=network_driver,
            platform=platform,
        )
        return await loop.run_in_executor(
            self._executor,
            _sync_get_configs,
            host,
            device_type,
            username,
            password,
            include_running,
            include_startup,
        )


def _session(
    host: str,
    device_type: str,
    username: str,
    password: str,
) -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host=host,
        device_type=device_type,
        username=username,
        password=password,
    )


def _sync_send_commands(
    host: str,
    device_type: str,
    username: str,
    password: str,
    commands: list[str],
    privileged: bool,
    use_textfsm: bool,
) -> CommandResult:
    with _session(host, device_type, username, password) as session:
        session.connect(privileged=privileged)
        return session.send_commands(commands, use_textfsm=use_textfsm)


def _sync_get_running_config(
    host: str,
    device_type: str,
    username: str,
    password: str,
) -> str:
    with _session(host, device_type, username, password) as session:
        return session.get_running_config()


def _sync_get_startup_config(
    host: str,
    device_type: str,
    username: str,
    password: str,
) -> str:
    with _session(host, device_type, username, password) as session:
        return session.get_startup_config()


def _sync_get_configs(
    host: str,
    device_type: str,
    username: str,
    password: str,
    include_running: bool,
    include_startup: bool,
) -> ConfigResult:
    with _session(host, device_type, username, password) as session:
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
