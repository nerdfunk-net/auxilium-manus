"""Low-level Netmiko SSH session helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_SESSION_TIMEOUT = 60
DEFAULT_READ_TIMEOUT = 60


@dataclass
class CommandResult:
    success: bool
    output: str = ""
    command_outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ConfigResult:
    success: bool
    running_config: str | None = None
    startup_config: str | None = None
    error: str | None = None


@dataclass
class DeployResult:
    success: bool
    config_output: str = ""
    save_output: str | None = None
    error: str | None = None


class NetmikoConnectionError(Exception):
    """Raised when connection or command execution fails."""


def serialize_command_output(raw: Any) -> str:
    """Normalize Netmiko command output (including TextFSM structures) to text."""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, indent=2, default=str)


class NetmikoDeviceSession:
    """Synchronous Netmiko session with explicit connect / disconnect."""

    def __init__(
        self,
        *,
        host: str,
        device_type: str,
        username: str,
        password: str,
        timeout: int = DEFAULT_TIMEOUT,
        session_timeout: int = DEFAULT_SESSION_TIMEOUT,
    ) -> None:
        self.host = host.split("/")[0] if "/" in host else host
        self.device_type = device_type
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session_timeout = session_timeout
        self._connection: ConnectHandler | None = None

    def connect(self, *, privileged: bool = True) -> None:
        if self._connection is not None:
            return

        device_params: dict[str, Any] = {
            "device_type": self.device_type,
            "host": self.host,
            "username": self.username,
            "password": self.password,
            "timeout": self.timeout,
            "session_timeout": self.session_timeout,
        }

        try:
            logger.info("Connecting to %s (type=%s)", self.host, self.device_type)
            self._connection = ConnectHandler(**device_params)
            if privileged:
                self.enable()
            logger.info("Connected to %s", self.host)
        except NetmikoTimeoutException as exc:
            raise NetmikoConnectionError(f"Connection timeout: {exc}") from exc
        except NetmikoAuthenticationException as exc:
            raise NetmikoConnectionError(f"Authentication failed: {exc}") from exc
        except Exception as exc:
            raise NetmikoConnectionError(f"Connection failed: {exc}") from exc

    def disconnect(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.disconnect()
        finally:
            self._connection = None
            logger.info("Disconnected from %s", self.host)

    def __enter__(self) -> NetmikoDeviceSession:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    @property
    def connection(self) -> ConnectHandler:
        if self._connection is None:
            raise NetmikoConnectionError("Not connected")
        return self._connection

    def enable(self) -> None:
        try:
            self.connection.enable()
        except Exception as exc:
            logger.warning("Failed to enter privileged mode on %s: %s", self.host, exc)

    def send_command(
        self,
        command: str,
        *,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        use_textfsm: bool = False,
    ) -> str:
        self.connect()
        try:
            return self.connection.send_command(
                command,
                use_textfsm=use_textfsm,
                read_timeout=read_timeout,
            )
        except Exception as exc:
            raise NetmikoConnectionError(
                f"Command {command!r} failed on {self.host}: {exc}"
            ) from exc

    def send_commands(
        self,
        commands: list[str],
        *,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        use_textfsm: bool = False,
    ) -> CommandResult:
        self.connect()
        outputs: dict[str, str] = {}
        combined: list[str] = []

        try:
            for command in commands:
                raw = self.connection.send_command(
                    command,
                    use_textfsm=use_textfsm,
                    read_timeout=read_timeout,
                )
                text = serialize_command_output(raw)
                outputs[command] = text
                combined.append(text)
            return CommandResult(
                success=True,
                output="\n".join(combined),
                command_outputs=outputs,
            )
        except Exception as exc:
            return CommandResult(success=False, output="\n".join(combined), error=str(exc))

    def deploy_config(
        self,
        commands: list[str],
        *,
        mode: str,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
    ) -> DeployResult:
        self.connect()
        try:
            if mode == "config_mode":
                output = self.connection.send_config_set(commands, read_timeout=read_timeout)
            else:
                outputs = [
                    self.connection.send_command(command, read_timeout=read_timeout)
                    for command in commands
                ]
                output = "\n".join(serialize_command_output(item) for item in outputs)
            return DeployResult(success=True, config_output=serialize_command_output(output))
        except Exception as exc:
            return DeployResult(success=False, error=str(exc))

    def save_running_config(self) -> str:
        try:
            return self.connection.save_config(confirm=True)
        except Exception as exc:
            raise NetmikoConnectionError(
                f"Failed to save running-config to startup-config on {self.host}: {exc}"
            ) from exc

    def get_running_config(self) -> str:
        return self.send_command("show running-config", read_timeout=120)

    def get_startup_config(self) -> str:
        return self.send_command("show startup-config", read_timeout=120)

    def get_configs(self) -> ConfigResult:
        try:
            running = self.get_running_config()
            startup = self.get_startup_config()
            return ConfigResult(
                success=True,
                running_config=running,
                startup_config=startup,
            )
        except NetmikoConnectionError as exc:
            return ConfigResult(success=False, error=str(exc))
        except Exception as exc:
            return ConfigResult(success=False, error=str(exc))
