"""Low-level Netmiko SSH session helpers."""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_SESSION_TIMEOUT = 60
DEFAULT_READ_TIMEOUT = 60

# Cisco IOS/IOS-XE raises a "...[confirm]" style interactive prompt for
# certain destructive/careful config commands (e.g. "no username <user>").
# Netmiko has no generic hook for answering this mid-command inside
# send_config_set(); auto_confirm_prompts opts into a manual per-command
# loop that watches for this cue and answers it (see deploy_config()).
_CONFIRMATION_CUE = "confirm"


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
    session_log: str | None = None
    confirmed_prompts: list[str] = field(default_factory=list)


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
        capture_session_log: bool = True,
    ) -> None:
        self.host = host.split("/")[0] if "/" in host else host
        self.device_type = device_type
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session_timeout = session_timeout
        self._connection: ConnectHandler | None = None
        self._session_log_buffer: io.BytesIO | None = (
            io.BytesIO() if capture_session_log else None
        )

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
            "session_log": self._session_log_buffer,
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

    def get_session_log(self) -> str | None:
        """Return the raw CLI byte stream captured so far, decoded as text.

        Useful for diagnosing a failed command: the buffer still holds
        everything the device sent up to the point of failure even when an
        exception aborts the call before it returns normally.
        """
        if self._session_log_buffer is None:
            return None
        raw = self._session_log_buffer.getvalue()
        if not raw:
            return None
        return raw.decode("utf-8", errors="replace")

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

    def _confirm_prompt_pattern(self) -> str:
        base_prompt = re.escape(getattr(self.connection, "base_prompt", ""))
        return rf"(?:{base_prompt}.*$|#\s*$|{_CONFIRMATION_CUE})"

    def _send_command_confirming(
        self, command: str, *, read_timeout: int
    ) -> tuple[str, bool]:
        """Send one command; if it raises a Cisco-style '[confirm]' prompt,
        answer it with Enter (the IOS default/yes response) and keep reading
        until the real prompt returns. Returns (output, was_confirmed)."""
        output = self.connection.send_command(
            command,
            expect_string=self._confirm_prompt_pattern(),
            read_timeout=read_timeout,
        )
        if _CONFIRMATION_CUE not in output.lower():
            return output, False
        self.connection.write_channel(self.connection.RETURN)
        output += self.connection.read_until_prompt(
            read_timeout=read_timeout, read_entire_line=True
        )
        return output, True

    def _send_config_set_confirming(
        self, commands: list[str], *, read_timeout: int
    ) -> tuple[str, list[str]]:
        """Manual replacement for send_config_set() that can answer an
        embedded confirmation prompt raised by an individual command.
        Only used when auto_confirm_prompts is enabled — send_config_set()
        has no hook for answering a prompt mid-stream."""
        confirmed: list[str] = []
        outputs: list[str] = [self.connection.config_mode()]
        for command in commands:
            text, was_confirmed = self._send_command_confirming(
                command, read_timeout=read_timeout
            )
            outputs.append(text)
            if was_confirmed:
                confirmed.append(command)
        outputs.append(self.connection.exit_config_mode())
        return "\n".join(outputs), confirmed

    def deploy_config(
        self,
        commands: list[str],
        *,
        mode: str,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        auto_confirm_prompts: bool = False,
    ) -> DeployResult:
        self.connect()
        try:
            confirmed: list[str] = []
            if mode == "config_mode" and auto_confirm_prompts:
                output, confirmed = self._send_config_set_confirming(
                    commands, read_timeout=read_timeout
                )
            elif mode == "config_mode":
                output = self.connection.send_config_set(commands, read_timeout=read_timeout)
            elif auto_confirm_prompts:
                outputs = []
                for command in commands:
                    text, was_confirmed = self._send_command_confirming(
                        command, read_timeout=read_timeout
                    )
                    outputs.append(text)
                    if was_confirmed:
                        confirmed.append(command)
                output = "\n".join(serialize_command_output(item) for item in outputs)
            else:
                outputs = [
                    self.connection.send_command(command, read_timeout=read_timeout)
                    for command in commands
                ]
                output = "\n".join(serialize_command_output(item) for item in outputs)
            return DeployResult(
                success=True,
                config_output=serialize_command_output(output),
                confirmed_prompts=confirmed,
            )
        except Exception as exc:
            return DeployResult(
                success=False, error=str(exc), session_log=self.get_session_log()
            )

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
