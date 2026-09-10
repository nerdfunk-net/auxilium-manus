"""Low-level Netmiko SSH session helpers."""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from netmiko import ConnectHandler, file_transfer
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

# "copy <src> running-config" asks one interactive question,
# "Destination filename [running-config]? ", which must be answered with Enter
# (see merge_running_config()). The file itself then loads in IOS
# non-interactive batch mode, so per-line "[confirm]" prompts are handled by the
# copy engine -- we still watch for _CONFIRMATION_CUE defensively.
_MERGE_DESTINATION_CUE = "destination filename"
_MERGE_PROMPT_CUES = (_MERGE_DESTINATION_CUE, _CONFIRMATION_CUE)
# Expected real answer count is 1; the bound stops an unexpected prompt loop
# from hanging one read_timeout per iteration forever.
_MERGE_MAX_PROMPT_ANSWERS = 5
# IOS keeps loading (and returns to the prompt) after these lines, so netmiko
# sees a clean success -- merge_running_config() scans the transcript for them.
_COPY_ERROR_MARKERS = ("%error", "invalid input", "%warning")


@dataclass
class CommandResult:
    success: bool
    output: str = ""
    command_outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    confirmed_prompts: list[str] = field(default_factory=list)


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


@dataclass
class FileTransferResult:
    success: bool
    file_transferred: bool = False
    file_verified: bool = False
    file_exists: bool = False
    error: str | None = None


class NetmikoConnectionError(Exception):
    """Raised when connection or command execution fails."""


def serialize_command_output(raw: Any) -> str:
    """Normalize Netmiko command output (including TextFSM structures) to text."""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, indent=2, default=str)


# Cisco IOS/IOS-XE prints "Building configuration...\n\nCurrent configuration :
# <n> bytes\n" ahead of the actual config text on 'show running-config'.
# Netmiko's send_command() only strips the command echo and trailing prompt,
# so this banner survives verbatim -- and it is not valid config syntax: any
# consumer that later feeds this text back to the device (e.g. 'configure
# replace') sees it as two commands, fails to apply them, and aborts.
_RUNNING_CONFIG_BUILDING_LINE = "building configuration..."
_RUNNING_CONFIG_SIZE_LINE_RE = re.compile(r"^current configuration\s*:\s*\d+\s*bytes\s*$", re.I)


def _strip_running_config_banner(raw: str) -> str:
    """Drop the 'Building configuration...'/'Current configuration : N bytes'
    preamble (and any blank lines around it) so callers get the config text a
    device would actually accept back, matching what 'show startup-config' or
    an on-device saved config file looks like."""
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
        elif stripped.lower() == _RUNNING_CONFIG_BUILDING_LINE:
            index += 1
        elif _RUNNING_CONFIG_SIZE_LINE_RE.match(stripped):
            index += 1
        else:
            break
    return "\n".join(lines[index:])


def _copy_error_in(output: str) -> str | None:
    """Return the offending line when a ``copy <src> running-config`` load
    reported a device-side error, else ``None``.

    IOS keeps loading (and still returns to the prompt) after an
    ``%Error opening ...`` line, a bad ``%Warning ...`` line, or an
    ``Invalid input detected ...`` line, so netmiko sees a clean success -- the
    transcript has to be scanned to notice the merge did not actually apply.
    """
    lowered = output.lower()
    for marker in _COPY_ERROR_MARKERS:
        if marker in lowered:
            for line in output.splitlines():
                if marker in line.lower():
                    return line.strip()
            return marker
    return None


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
        keepalive: int = 30,
    ) -> None:
        self.host = host.split("/")[0] if "/" in host else host
        self.device_type = device_type
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session_timeout = session_timeout
        self.keepalive = keepalive
        self._connection: ConnectHandler | None = None
        self._session_log_buffer: io.BytesIO | None = io.BytesIO() if capture_session_log else None

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
            "keepalive": self.keepalive,
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

    def is_alive(self) -> bool:
        """True when the underlying transport is still connected.

        Used by DeviceSessionPool to decide whether to reuse this session or
        transparently reconnect (e.g. after a device-side exec-timeout).
        """
        if self._connection is None:
            return False
        try:
            return bool(self._connection.is_alive())
        except Exception:
            return False

    def check_config_mode(self) -> bool:
        """True when the session is currently sitting in config mode.

        Used by DeviceSessionPool's debug-only post-op guard (see
        doc/DURABLE_SSH_SESSION.md §7) to catch an executor that left a
        pooled session in a non-base state.
        """
        try:
            return bool(self.connection.check_config_mode())
        except Exception:
            return False

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
        auto_confirm_prompts: bool = False,
    ) -> CommandResult:
        if auto_confirm_prompts and use_textfsm:
            # Confirm-handling reads output via expect_string; textfsm-parsed structures
            # aren't strings, so the confirm-cue check in _send_command_confirming can't
            # apply. Callers must resolve parsing before turning this on.
            raise ValueError(
                "send_commands: use_textfsm and auto_confirm_prompts are mutually exclusive"
            )

        self.connect()
        outputs: dict[str, str] = {}
        combined: list[str] = []
        confirmed: list[str] = []

        try:
            for command in commands:
                if auto_confirm_prompts:
                    text, was_confirmed = self._send_command_confirming(
                        command, read_timeout=read_timeout
                    )
                    if was_confirmed:
                        confirmed.append(command)
                else:
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
                confirmed_prompts=confirmed,
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                output="\n".join(combined),
                command_outputs=outputs,
                error=str(exc),
                confirmed_prompts=confirmed,
            )

    def _confirm_prompt_pattern(self, *, extra_cues: tuple[str, ...] = ()) -> str:
        base_prompt = re.escape(getattr(self.connection, "base_prompt", ""))
        alternatives = [rf"{base_prompt}.*$", r"#\s*$", _CONFIRMATION_CUE]
        # Netmiko compiles this string case-sensitively; IOS prints the merge
        # prompt as "Destination filename ...", so match extra cues case-insensitively.
        alternatives.extend(rf"(?i:{re.escape(cue)})" for cue in extra_cues)
        return rf"(?:{'|'.join(alternatives)})"

    def _send_command_confirming(self, command: str, *, read_timeout: int) -> tuple[str, bool]:
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

    def merge_running_config(
        self,
        source_filename: str,
        *,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
    ) -> CommandResult:
        """Run ``copy <source_filename> running-config`` and answer its one
        interactive prompt -- ``Destination filename [running-config]? `` -- with
        Enter, then read through to the privileged-exec base ``#`` prompt.

        IOS runs the file in non-interactive batch mode, so per-line
        ``[confirm]`` prompts are auto-bypassed by the copy engine; in practice
        there is exactly one prompt (or none, with ``file prompt quiet``). The
        answer step is still wrapped in a small bounded loop
        (``<= _MERGE_MAX_PROMPT_ANSWERS``) so an unexpected extra prompt is
        nudged with Enter instead of hanging until ``read_timeout``.

        The session is always left at the base prompt on return (or, on the
        exception path, left for the pool to reconnect lazily) so a later step
        can safely reuse it -- see doc/DURABLE_SSH_SESSION.md.
        """
        self.connect()
        command = f"copy {source_filename} running-config"
        pattern = self._confirm_prompt_pattern(extra_cues=(_MERGE_DESTINATION_CUE,))
        cue_re = re.compile("|".join(re.escape(cue) for cue in _MERGE_PROMPT_CUES), re.I)
        answered: list[str] = []

        try:
            # Stops at the "Destination filename" prompt, or -- with
            # "file prompt quiet" -- straight back at the base prompt.
            output = self.connection.send_command(
                command, expect_string=pattern, read_timeout=read_timeout
            )
            chunk = output

            for _ in range(_MERGE_MAX_PROMPT_ANSWERS):
                match = cue_re.search(chunk)
                if match is None:
                    break  # last read ended on the base-prompt alternative
                answered.append(match.group(0).lower())
                self.connection.write_channel(self.connection.RETURN)
                # read_until_pattern (NOT read_until_prompt): returns at the next
                # cue OR the base prompt, whichever comes first. re.M so the
                # ``<base>.*$`` / ``#\s*$`` alternatives anchor per line, matching
                # how netmiko's own send_command(expect_string=...) searches.
                chunk = self.connection.read_until_pattern(
                    pattern=pattern, read_timeout=read_timeout, re_flags=re.M
                )
                output += chunk
            else:
                # Loop exhausted with a prompt still pending. Drain to the base
                # prompt so the pooled session stays usable, then fail.
                self.connection.write_channel(self.connection.RETURN)
                output += self.connection.read_until_prompt(
                    read_timeout=read_timeout, read_entire_line=True
                )
                return CommandResult(
                    success=False,
                    output=output,
                    command_outputs={command: output},
                    error=(
                        f"{command!r} still prompting after "
                        f"{_MERGE_MAX_PROMPT_ANSWERS} answered prompt(s); aborted"
                    ),
                    confirmed_prompts=answered,
                )

            error = _copy_error_in(output)
            if error is not None:
                return CommandResult(
                    success=False,
                    output=output,
                    command_outputs={command: output},
                    error=error,
                    confirmed_prompts=answered,
                )
            return CommandResult(
                success=True,
                output=output,
                command_outputs={command: output},
                confirmed_prompts=answered,
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                output="",
                command_outputs={},
                error=str(exc),
                confirmed_prompts=answered,
            )

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
            text, was_confirmed = self._send_command_confirming(command, read_timeout=read_timeout)
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
            return DeployResult(success=False, error=str(exc), session_log=self.get_session_log())

    def save_running_config(self) -> str:
        try:
            return self.connection.save_config(confirm=True)
        except Exception as exc:
            raise NetmikoConnectionError(
                f"Failed to save running-config to startup-config on {self.host}: {exc}"
            ) from exc

    def get_running_config(self) -> str:
        return _strip_running_config_banner(
            self.send_command("show running-config", read_timeout=120)
        )

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

    def upload_file(
        self,
        *,
        local_path: str,
        dest_file: str,
        file_system: str,
        overwrite: bool = False,
        inline_transfer: bool = False,
        socket_timeout: float = 10.0,
    ) -> FileTransferResult:
        """Push a local file to the device via Netmiko's SCP/SFTP file_transfer,
        or its inline (non-SCP, text-only) transfer mode.

        Uses its own SCP/SFTP subsystem channel over the existing SSH
        transport, so it does not enter config mode or otherwise change the
        CLI session's base state.
        """
        self.connect()
        try:
            result = file_transfer(
                self.connection,
                source_file=local_path,
                dest_file=dest_file,
                file_system=file_system,
                direction="put",
                overwrite_file=overwrite,
                inline_transfer=inline_transfer,
                socket_timeout=socket_timeout,
            )
            return FileTransferResult(
                success=True,
                file_transferred=bool(result.get("file_transferred")),
                file_verified=bool(result.get("file_verified")),
                file_exists=bool(result.get("file_exists")),
            )
        except Exception as exc:
            return FileTransferResult(success=False, error=str(exc))
