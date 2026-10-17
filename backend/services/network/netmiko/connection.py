"""Low-level Netmiko SSH session helpers."""

from __future__ import annotations

import io
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from netmiko import ConnectHandler, file_transfer
from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from models.failure import FailureInfo, FailurePhase
from services.network.netmiko.failure import classify_netmiko_exception
from services.network.netmiko.output_check import (
    CONFIG_ERROR_PATTERN,
    find_cli_error,
    find_commit_error,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_SESSION_TIMEOUT = 60
DEFAULT_READ_TIMEOUT = 60
DEFAULT_CONFIG_READ_TIMEOUT = 120

# Cisco IOS/IOS-XE raises a "...[confirm]" style interactive prompt for
# certain destructive/careful config commands (e.g. "no username <user>").
# Netmiko has no generic hook for answering this mid-command inside
# send_config_set(); auto_confirm_prompts opts into a manual per-command
# loop that watches for this cue and answers it (see deploy_config()).
_CONFIRMATION_CUE = "[confirm]"

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


# Netmiko ignores the reply to its session-setup commands (``terminal width``, ``terminal length
# 0``), so a device that refuses them (typically TACACS+/RADIUS command authorization) still
# yields a "successful" connect -- and the first paged ``show`` then hangs at ``--More--``.
# Markers are matched case-insensitively against the raw session log; only the closed label
# is ever reported, never the device text.
_SETUP_REJECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("authorization failed", "authorization_failed"),
)
SETUP_REJECTION_NOTE = (
    "the device rejected a session-setup command such as 'terminal length 0' "
    "(AAA command authorization?), so output may be paged"
)


def setup_rejection_in(session_log: str) -> str | None:
    """Closed label (``"authorization_failed"``) when the connect-phase *session_log* shows the
    device refusing a setup command, else ``None``."""
    lowered = session_log.lower()
    for marker, label in _SETUP_REJECTION_MARKERS:
        if marker in lowered:
            return label
    return None


def _is_awaiting_answer(output: str) -> bool:
    """True when *output* ends on an unanswered interactive prompt.

    Both cues -- the literal ``[confirm]`` and "Destination filename" -- are only honoured on
    the last non-empty line, so the words appearing earlier in the output (a log, a banner,
    ``show logging`` text) are never mistaken for a pending prompt (C2-11).
    """
    last_line = output.rstrip().rsplit("\n", 1)[-1].lower()
    return _CONFIRMATION_CUE in last_line or _MERGE_DESTINATION_CUE in last_line


# IOS-XR and Junos keep a candidate configuration: without a commit, exit_config_mode() discards
# it (XR answers "no") or leaves it uncommitted (Junos answers "yes"), so a deploy would report
# success while nothing is applied.
_COMMIT_MODEL_TYPES = frozenset({"cisco_xr", "juniper_junos", "juniper"})
_NETMIKO_REJECTION = re.compile(r"at command: (?P<command>.*?), matched error:", re.S)


def _command_index(commands: list[str], exception_text: str) -> int | None:
    """Index of the refused command, parsed from Netmiko's ``ConfigInvalidException`` text.

    The text contains the refused command (possibly a rendered secret), so it is parsed for the
    index only and never stored."""
    match = _NETMIKO_REJECTION.search(exception_text)
    if match is None:
        return None
    refused = match.group("command").strip()
    for index, command in enumerate(commands):
        if command.strip() == refused:
            return index
    return None


@dataclass
class CommandResult:
    success: bool
    output: str = ""
    command_outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    confirmed_prompts: list[str] = field(default_factory=list)
    failure: FailureInfo | None = None


@dataclass
class ConfigResult:
    success: bool
    running_config: str | None = None
    startup_config: str | None = None
    error: str | None = None
    failure: FailureInfo | None = None


@dataclass
class DeployResult:
    success: bool
    config_output: str = ""
    save_output: str | None = None
    error: str | None = None
    session_log: str | None = None
    confirmed_prompts: list[str] = field(default_factory=list)
    failure: FailureInfo | None = None


@dataclass
class FileTransferResult:
    success: bool
    file_transferred: bool = False
    file_verified: bool = False
    file_exists: bool = False
    error: str | None = None
    failure: FailureInfo | None = None


class NetmikoConnectionError(Exception):
    """Raised when connection or command execution fails.

    ``failure`` is the structured, non-sensitive classification of the cause (see
    ``models.failure``); callers copy it onto the ``DeviceError`` they record.
    """

    def __init__(self, message: str, *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff schedule for a flaky connect-phase timeout (e.g. an unstable WAN
    link to a device). ``backoff_seconds[i]`` is the wait before retry ``i+1``;
    an empty tuple means no retry. Never applied to auth failures — see
    ``NetmikoDeviceSession.connect()``."""

    backoff_seconds: tuple[int, ...] = ()

    @property
    def max_attempts(self) -> int:
        return len(self.backoff_seconds) + 1


# (kind, level, message) — reports connect-phase progress for live run events.
# Invoked on the pool's worker thread; see services/execution/run_events_reporter.py.
ConnectEventCallback = Callable[[str, str, str], None]
_EVENT_DETAIL_MAX = 200


def _notify(on_event: ConnectEventCallback | None, kind: str, level: str, message: str) -> None:
    """Report a connect-phase event; a broken callback must never fail a connect."""
    if on_event is None:
        return
    try:
        on_event(kind, level, message)
    except Exception:
        logger.warning("Connect event callback failed kind=%s", kind, exc_info=True)


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
        # ConnectHandler is a factory function, not a class; the real type is picked by device_type.
        self._connection: Any = None
        self._session_log_buffer: io.BytesIO | None = io.BytesIO() if capture_session_log else None
        self._setup_rejection: str | None = None

    def connect(
        self,
        *,
        privileged: bool = True,
        retry: RetryPolicy | None = None,
        on_event: ConnectEventCallback | None = None,
    ) -> None:
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

        max_attempts = retry.max_attempts if retry else 1
        started = time.monotonic()

        def _failure(exc: Exception, attempt: int) -> FailureInfo:
            return classify_netmiko_exception(
                exc,
                phase="connect",
                attempts=attempt,
                max_attempts=max_attempts,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "Connecting to %s (type=%s) attempt=%d/%d",
                    self.host,
                    self.device_type,
                    attempt,
                    max_attempts,
                )
                _notify(
                    on_event,
                    "connect_attempt",
                    "info",
                    f"Connecting to {self.host} (attempt {attempt}/{max_attempts})",
                )
                log_offset = self._session_log_size()
                self._connection = ConnectHandler(**device_params)
                self._check_setup_rejection(on_event, since=log_offset)
                if privileged:
                    self.enable()
                logger.info("Connected to %s", self.host)
                _notify(on_event, "connected", "info", f"Connected to {self.host}")
                return
            except NetmikoTimeoutException as exc:
                if retry and attempt < max_attempts:
                    delay = retry.backoff_seconds[attempt - 1]
                    logger.warning(
                        "Connection timeout to %s on attempt %d/%d, retrying in %ds",
                        self.host,
                        attempt,
                        max_attempts,
                        delay,
                    )
                    _notify(
                        on_event,
                        "connect_retry",
                        "warning",
                        f"Connection timeout to {self.host} on attempt {attempt}/{max_attempts}, "
                        f"retrying in {delay}s",
                    )
                    time.sleep(delay)
                    continue
                _notify(
                    on_event,
                    "connect_failed",
                    "error",
                    f"Connection timeout to {self.host} after {attempt} attempt(s): "
                    f"{str(exc)[:_EVENT_DETAIL_MAX]}",
                )
                raise NetmikoConnectionError(
                    f"Connection timeout: {exc}", failure=_failure(exc, attempt)
                ) from exc
            except NetmikoAuthenticationException as exc:
                # Deliberately no exception text: it can echo credentials.
                _notify(on_event, "auth_failed", "error", f"Authentication failed for {self.host}")
                raise NetmikoConnectionError(
                    f"Authentication failed: {exc}", failure=_failure(exc, attempt)
                ) from exc
            except Exception as exc:
                _notify(
                    on_event,
                    "connect_failed",
                    "error",
                    f"Connection to {self.host} failed ({type(exc).__name__}): "
                    f"{str(exc)[:_EVENT_DETAIL_MAX]}",
                )
                raise NetmikoConnectionError(
                    f"Connection failed: {exc}", failure=_failure(exc, attempt)
                ) from exc

    def _session_log_size(self) -> int:
        return len(self._session_log_buffer.getvalue()) if self._session_log_buffer else 0

    def _check_setup_rejection(self, on_event: ConnectEventCallback | None, *, since: int) -> None:
        """Flag (and report) a device that refused Netmiko's session-setup commands.

        Only the log written by this connect (from byte *since*) is scanned: the buffer
        outlives reconnects, and earlier command output must not taint a fresh session."""
        window = b""
        if self._session_log_buffer is not None:
            window = self._session_log_buffer.getvalue()[since:]
        self._setup_rejection = setup_rejection_in(window.decode("utf-8", errors="replace"))
        if self._setup_rejection is None:
            return
        logger.warning("Device %s rejected a session-setup command", self.host)
        _notify(
            on_event,
            "setup_rejected",
            "warning",
            f"{self.host}: {SETUP_REJECTION_NOTE}",
        )

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
    def connection(self) -> Any:
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

    def _classify_failure(
        self, exc: BaseException, *, phase: FailurePhase, message: str
    ) -> tuple[FailureInfo, str]:
        """Classify *exc*; a timeout on a session whose setup commands were refused is a
        symptom of paged output, so it becomes ``permission_denied`` and *message* gets the
        explanatory note."""
        failure = classify_netmiko_exception(exc, phase=phase)
        if self._setup_rejection and failure.kind == "command_timeout":
            failure = failure.model_copy(
                update={"kind": "permission_denied", "hint": "check_permissions"}
            )
            message = f"{message} ({SETUP_REJECTION_NOTE})"
        return failure, message

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
            failure, error = self._classify_failure(
                exc, phase="command", message=f"Command {command!r} failed on {self.host}: {exc}"
            )
            raise NetmikoConnectionError(error, failure=failure) from exc

    def send_commands(
        self,
        commands: list[str],
        *,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        use_textfsm: bool = False,
        auto_confirm_prompts: bool = False,
        fail_on_cli_error: bool = False,
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
                refusal = find_cli_error(text) if fail_on_cli_error else None
                if refusal is not None:
                    return CommandResult(
                        success=False,
                        output="\n".join(combined),
                        command_outputs=outputs,
                        error=(
                            f"The device rejected command {len(outputs)} of {len(commands)} "
                            f"({refusal.label}); the remaining commands were not sent"
                        ),
                        confirmed_prompts=confirmed,
                        failure=FailureInfo(
                            phase="command", kind="command_error", hint="check_command_syntax"
                        ),
                    )
            return CommandResult(
                success=True,
                output="\n".join(combined),
                command_outputs=outputs,
                confirmed_prompts=confirmed,
            )
        except Exception as exc:
            failure, error = self._classify_failure(exc, phase="command", message=str(exc))
            return CommandResult(
                success=False,
                output="\n".join(combined),
                command_outputs=outputs,
                error=error,
                confirmed_prompts=confirmed,
                failure=failure,
            )

    def _confirm_prompt_pattern(self, *, extra_cues: tuple[str, ...] = ()) -> str:
        base_prompt = re.escape(getattr(self.connection, "base_prompt", ""))
        alternatives = [rf"{base_prompt}.*$", r"#\s*$", re.escape(_CONFIRMATION_CUE)]
        # Netmiko compiles this string case-sensitively; IOS prints the merge
        # prompt as "Destination filename ...", so match extra cues case-insensitively.
        alternatives.extend(rf"(?i:{re.escape(cue)})" for cue in extra_cues)
        return rf"(?:{'|'.join(alternatives)})"

    def _send_command_confirming(self, command: str, *, read_timeout: int) -> tuple[str, bool]:
        """Send one command; if it raises a Cisco-style '[confirm]' prompt or a
        'Destination filename [...]?' prompt (``copy running-config
        startup-config``), answer it with Enter (the IOS default/yes response)
        and keep reading until the real prompt returns.
        Returns (output, was_confirmed)."""
        output = self.connection.send_command(
            command,
            expect_string=self._confirm_prompt_pattern(extra_cues=(_MERGE_DESTINATION_CUE,)),
            read_timeout=read_timeout,
        )
        if not _is_awaiting_answer(output):
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
                    failure=FailureInfo(phase="config", kind="command_error"),
                )

            error = _copy_error_in(output)
            if error is not None:
                return CommandResult(
                    success=False,
                    output=output,
                    command_outputs={command: output},
                    error=error,
                    confirmed_prompts=answered,
                    failure=FailureInfo(
                        phase="config", kind="config_rejected", hint="check_command_syntax"
                    ),
                )
            return CommandResult(
                success=True,
                output=output,
                command_outputs={command: output},
                confirmed_prompts=answered,
            )
        except Exception as exc:
            failure, error = self._classify_failure(exc, phase="config", message=str(exc))
            return CommandResult(
                success=False,
                output="",
                command_outputs={},
                error=error,
                confirmed_prompts=answered,
                failure=failure,
            )

    def _send_config_set_confirming(
        self, commands: list[str], *, read_timeout: int, stop_on_error: bool = False
    ) -> tuple[str, list[str], int | None]:
        """Manual replacement for send_config_set() that can answer an
        embedded confirmation prompt raised by an individual command.
        Only used when auto_confirm_prompts is enabled — send_config_set()
        has no hook for answering a prompt mid-stream.

        Stays in config mode (the caller commits and leaves it). Returns
        ``(output, confirmed, rejected_at)``; with ``stop_on_error`` the walk stops at the first
        refused command and ``rejected_at`` is its index."""
        confirmed: list[str] = []
        outputs: list[str] = [self.connection.config_mode()]
        rejected_at: int | None = None
        for index, command in enumerate(commands):
            text, was_confirmed = self._send_command_confirming(command, read_timeout=read_timeout)
            outputs.append(text)
            if was_confirmed:
                confirmed.append(command)
            if stop_on_error and find_cli_error(text) is not None:
                rejected_at = index
                break
        return "\n".join(outputs), confirmed, rejected_at

    def _send_exec_commands(
        self,
        commands: list[str],
        *,
        read_timeout: int,
        auto_confirm: bool,
        stop_on_error: bool,
    ) -> tuple[str, list[str], int | None]:
        confirmed: list[str] = []
        outputs: list[str] = []
        rejected_at: int | None = None
        for index, command in enumerate(commands):
            if auto_confirm:
                text, was_confirmed = self._send_command_confirming(
                    command, read_timeout=read_timeout
                )
                if was_confirmed:
                    confirmed.append(command)
            else:
                text = serialize_command_output(
                    self.connection.send_command(command, read_timeout=read_timeout)
                )
            outputs.append(text)
            if stop_on_error and find_cli_error(text) is not None:
                rejected_at = index
                break
        return "\n".join(outputs), confirmed, rejected_at

    def _leave_config_mode(self, *, best_effort: bool = False) -> str:
        """Leave config mode; a failed config operation must never hand a pooled session back
        while it still sits in config mode (C2-05)."""
        try:
            return self.connection.exit_config_mode()
        except Exception:
            if not best_effort:
                raise
            logger.debug("exit_config_mode failed host=%s", self.host, exc_info=True)
            return ""

    def _is_commit_model(self) -> bool:
        return self.device_type.removesuffix("_ssh") in _COMMIT_MODEL_TYPES

    def _commit_if_needed(self) -> str:
        """cisco_xr and juniper_junos keep a candidate configuration and need an explicit commit."""
        if not self._is_commit_model():
            return ""
        try:
            output = self.connection.commit(comment="manus deploy")
        except ValueError as exc:
            # Netmiko reports a refused commit as ValueError carrying the whole CLI transcript,
            # which can echo a rendered secret; never let that text reach the result (C2-01).
            logger.warning("commit refused host=%s: %s", self.host, type(exc).__name__)
            raise ConfigInvalidException("commit refused (commit_failed)") from None
        error = find_cli_error(output) or find_commit_error(output)
        if error is not None:
            raise ConfigInvalidException(f"commit refused ({error.label})")
        return output

    def _discard_candidate(self) -> None:
        """Junos keeps the candidate until it is rolled back; XR discards it on exit."""
        if self.device_type.removesuffix("_ssh") not in {"juniper_junos", "juniper"}:
            return
        try:
            self.connection.send_command_timing("rollback 0")
        except Exception:
            logger.debug("rollback 0 failed host=%s", self.host, exc_info=True)

    def _config_rejected(
        self,
        commands: list[str],
        index: int | None,
        label: str,
        output: str,
        confirmed: list[str],
        *,
        session_log: str | None = None,
    ) -> DeployResult:
        where = f"command {index + 1} of {len(commands)}" if index is not None else "a command"
        return DeployResult(
            success=False,
            config_output=output,
            confirmed_prompts=confirmed,
            session_log=session_log,
            error=f"The device rejected {where} ({label}); the remaining commands were not sent",
            failure=FailureInfo(
                phase="config", kind="config_rejected", hint="check_command_syntax"
            ),
        )

    def deploy_config(
        self,
        commands: list[str],
        *,
        mode: str,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        auto_confirm_prompts: bool = False,
        fail_on_cli_error: bool = True,
    ) -> DeployResult:
        self.connect()
        confirmed: list[str] = []
        try:
            rejected_at: int | None = None
            if mode == "config_mode" and auto_confirm_prompts:
                output, confirmed, rejected_at = self._send_config_set_confirming(
                    commands, read_timeout=read_timeout, stop_on_error=fail_on_cli_error
                )
            elif mode == "config_mode":
                output = self.connection.send_config_set(
                    commands,
                    read_timeout=read_timeout,
                    exit_config_mode=False,
                    error_pattern=CONFIG_ERROR_PATTERN if fail_on_cli_error else "",
                )
            else:
                output, confirmed, rejected_at = self._send_exec_commands(
                    commands,
                    read_timeout=read_timeout,
                    auto_confirm=auto_confirm_prompts,
                    stop_on_error=fail_on_cli_error,
                )
            if mode == "config_mode":
                if rejected_at is None:
                    output += self._commit_if_needed()
                else:
                    self._discard_candidate()
                output += self._leave_config_mode()
            if rejected_at is not None:
                error = find_cli_error(output)
                return self._config_rejected(
                    commands,
                    rejected_at,
                    error.label if error else "unknown",
                    serialize_command_output(output),
                    confirmed,
                )
            return DeployResult(
                success=True,
                config_output=serialize_command_output(output),
                confirmed_prompts=confirmed,
            )
        except ConfigInvalidException as exc:
            # Netmiko's error_pattern hit (or a commit was refused): never store its text.
            index = _command_index(commands, str(exc))
            if mode == "config_mode":
                self._discard_candidate()
                self._leave_config_mode(best_effort=True)
            return self._config_rejected(
                commands,
                index,
                "refused",
                "",
                confirmed,
                session_log=self.get_session_log(),
            )
        except Exception as exc:
            if mode == "config_mode":
                # leaving config mode on Junos answers the uncommitted-changes prompt with yes
                self._discard_candidate()
                self._leave_config_mode(best_effort=True)
            failure, error = self._classify_failure(exc, phase="config", message=str(exc))
            return DeployResult(
                success=False,
                error=error,
                session_log=self.get_session_log(),
                failure=failure,
            )

    def save_running_config(self) -> str:
        try:
            return self.connection.save_config(confirm=True)
        except Exception as exc:
            raise NetmikoConnectionError(
                f"Failed to save running-config to startup-config on {self.host}: {exc}"
            ) from exc

    def get_running_config(self, *, read_timeout: int = DEFAULT_CONFIG_READ_TIMEOUT) -> str:
        return _strip_running_config_banner(
            self.send_command("show running-config", read_timeout=read_timeout)
        )

    def get_startup_config(self, *, read_timeout: int = DEFAULT_CONFIG_READ_TIMEOUT) -> str:
        return self.send_command("show startup-config", read_timeout=read_timeout)

    def get_configs(
        self,
        *,
        read_timeout: int = DEFAULT_CONFIG_READ_TIMEOUT,
        include_running: bool = True,
        include_startup: bool = True,
    ) -> ConfigResult:
        try:
            running = (
                self.get_running_config(read_timeout=read_timeout) if include_running else None
            )
            startup = (
                self.get_startup_config(read_timeout=read_timeout) if include_startup else None
            )
            # A refused or empty show must not be stored as a "backup" (C2-07).
            for label, text in (("running", running), ("startup", startup)):
                if text is None:
                    continue
                error = find_cli_error(text)
                if error is not None or not text.strip():
                    return ConfigResult(
                        success=False,
                        error=(
                            f"The device did not return a usable {label}-config "
                            f"({error.label if error else 'empty'})"
                        ),
                        failure=FailureInfo(
                            phase="command", kind="command_error", hint="check_permissions"
                        ),
                    )
            return ConfigResult(
                success=True,
                running_config=running,
                startup_config=startup,
            )
        except NetmikoConnectionError as exc:
            return ConfigResult(success=False, error=str(exc), failure=exc.failure)
        except Exception as exc:
            return ConfigResult(
                success=False,
                error=str(exc),
                failure=classify_netmiko_exception(exc, phase="command"),
            )

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
            return FileTransferResult(
                success=False,
                error=str(exc),
                failure=classify_netmiko_exception(exc, phase="transfer"),
            )
