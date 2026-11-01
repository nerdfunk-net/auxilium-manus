"""What happens when the user clicks "Run" on a proposed device command (doc/AI_TOOL_CHAIN.md §29).

Nothing the proposal said is trusted. The signed token (``device_token``) says who may run which
commands on which device until when; this module checks it, runs the command policy again, resolves
the device again by name (it must still be the same device in the same source), loads the exact
secret values of the user *before* anything touches the device, runs the commands with the
credential the user picked, redacts the output, stores it behind a handle and writes one audit line.

The commands never come from the request body, the host never from anywhere but the inventory.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from services.ai_assistant.audit import log_device_command
from services.ai_assistant.command_policy import check_commands
from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.device_access import (
    DEVICE_DRIVERS,
    DeviceCommandOutput,
    DeviceCommandRunner,
    DeviceResolver,
    driver_known,
)
from services.ai_assistant.device_token import (
    DeviceCommandGrant,
    InvalidTokenError,
    verify_token,
)
from services.ai_assistant.known_secrets import try_load_visible_secret_values
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)

logger = logging.getLogger(__name__)

# user id -> runs open right now (one event loop thread, so plain integers are safe)
_open_runs: dict[int, int] = {}

MAX_OUTPUT_CHARS = 500_000
# What is read from the device and redacted before the shown size is applied (the result store
# also holds about this much).
MAX_RAW_CHARS = 2_000_000
# The whole run (connect, every command, disconnect) may take this long; Netmiko's own timeouts are
# per command, and up to five commands are allowed.
RUN_TIMEOUT_SECONDS = 300
# One person may have this many runs open at once (a run holds an SSH session). Counted in this
# process; the per-minute rate limit on the route is the cross-process bound.
MAX_RUNS_PER_USER = 2
MAX_ERROR_CHARS = 500
MAX_ERROR_RAW_CHARS = 5_000
# Slack for the error text, which is redacted by the same redactor as the output.
_REDACT_SLACK = 20_000
HANDLE_KIND = "device_command"


class InvalidConfirmationError(Exception):
    """The token is forged, expired or for another user."""


class DeviceChangedError(Exception):
    """The device name no longer points at the device the user confirmed."""


class TooManyRunsError(Exception):
    """The user already has the maximum number of device runs open."""


class SecretsUnavailableError(Exception):
    """The exact secret values could not be loaded, so the output cannot be scrubbed safely."""


@dataclass(frozen=True)
class DeviceCommandResult:
    success: bool
    error: str | None
    device_name: str
    commands: tuple[str, ...]
    output: str
    truncated: bool
    handle: str | None


def _join(outputs: Iterable[tuple[str, str]]) -> str:
    return "\n\n".join(f"$ {command}\n{raw.rstrip()}" for command, raw in outputs)


def _cut(text: str, limit: int) -> str:
    """The first ``limit`` characters, ending on a line boundary when one is near the end."""
    head = text[:limit]
    newline = head.rfind("\n")
    return head[:newline] if newline > limit // 2 else head


def _shape(raw_text: str, redact: Callable[[str], str]) -> tuple[str, bool]:
    """Redact first, cut second: a secret that straddles the cut is already gone.

    Output beyond ``MAX_RAW_CHARS`` is cut before redaction (the redactor has a budget) on a line
    boundary, so a one-line secret is never split; the result is then cut to the shown size.
    """
    truncated = len(raw_text) > MAX_RAW_CHARS
    if truncated:
        raw_text = _cut(raw_text, MAX_RAW_CHARS)
    text = redact(raw_text) if raw_text else ""
    if len(text) > MAX_OUTPUT_CHARS:
        shown = _cut(text, MAX_OUTPUT_CHARS)
        text = (
            f"{shown}\n…[output truncated: showed {len(shown)} of {len(text)} characters; "
            "the rest was left out]"
        )
        truncated = True
    return text, truncated


class DeviceCommandExecutor:
    def __init__(
        self,
        resolver: DeviceResolver,
        runner: DeviceCommandRunner,
        store: ResultStore | None,
        *,
        secret_loader: Callable[[int], list[str] | None] = try_load_visible_secret_values,
    ) -> None:
        self._resolver = resolver
        self._runner = runner
        self._store = store
        self._secret_loader = secret_loader

    async def execute(
        self,
        *,
        user_id: int,
        token: str,
        credential_id: int,
        network_driver: str | None = None,
    ) -> DeviceCommandResult:
        try:
            grant = verify_token(token, user_id=user_id)
        except InvalidTokenError as exc:
            raise InvalidConfirmationError from exc
        if _open_runs.get(user_id, 0) >= MAX_RUNS_PER_USER:
            raise TooManyRunsError
        _open_runs[user_id] = _open_runs.get(user_id, 0) + 1
        try:
            return await self._execute(user_id, grant, credential_id, network_driver)
        finally:
            remaining = _open_runs[user_id] - 1
            if remaining > 0:
                _open_runs[user_id] = remaining
            else:
                del _open_runs[user_id]

    async def _execute(
        self,
        user_id: int,
        grant: DeviceCommandGrant,
        credential_id: int,
        network_driver: str | None,
    ) -> DeviceCommandResult:
        # The signed commands are already normalised; running the policy again also refuses a token
        # that an older or buggy proposer signed, and anything that is not in normalised form.
        if network_driver is not None and network_driver not in DEVICE_DRIVERS:
            raise InvalidConfirmationError
        commands = check_commands(list(grant.commands))
        if tuple(commands) != grant.commands:
            raise InvalidConfirmationError
        secrets = await asyncio.to_thread(self._secret_loader, user_id)
        if secrets is None:
            raise SecretsUnavailableError
        device = await self._resolver.resolve(grant.device_name)
        # The address is part of what the user approved: if the inventory moved the device since
        # the card was shown, the run is refused and the user asks again.
        if (
            device.device_id != grant.device_id
            or device.source_id != grant.source_id
            or device.host != grant.host
        ):
            raise DeviceChangedError
        # The user's device type choice is only for a device whose platform the inventory does not
        # map (the card asks only then); a known driver is never replaced.
        chosen_driver = None if driver_known(device) else network_driver
        try:
            raw = await asyncio.wait_for(
                self._runner.run(
                    device,
                    commands,
                    credential_id=credential_id,
                    user_id=user_id,
                    network_driver=chosen_driver,
                ),
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raw = DeviceCommandOutput(
                False, f"The device did not finish within {RUN_TIMEOUT_SECONDS} seconds", ()
            )
        redactor = Redactor(max_chars=MAX_RAW_CHARS + _REDACT_SLACK)
        redactor.add_known_secrets(secrets)
        output, truncated = await asyncio.to_thread(_shape, _join(raw.outputs), redactor.redact)
        # Redact a generous prefix, then show the first MAX_ERROR_CHARS of it: a cut at the prefix
        # boundary is far beyond the part that is shown.
        error = (
            redactor.redact(raw.error[:MAX_ERROR_RAW_CHARS])[:MAX_ERROR_CHARS]
            if raw.error
            else None
        )
        handle = None
        if raw.success and output:
            handle = await self._store_output(user_id, output)
        log_device_command(
            user_id=user_id,
            device_id=device.device_id,
            command_hash=hashlib.sha256("\n".join(commands).encode()).hexdigest()[:12],
            outcome="ok" if raw.success else "failed",
            handle=handle,
        )
        return DeviceCommandResult(
            success=raw.success,
            error=error,
            device_name=device.name,
            commands=tuple(commands),
            output=output,
            truncated=truncated,
            handle=handle,
        )

    async def _store_output(self, user_id: int, output: str) -> str | None:
        if self._store is None:
            return None
        try:
            return await self._store.put(
                user_id, StoredResult(kind=HANDLE_KIND, data_class=DataClass.CONTENT, text=output)
            )
        except ResultStoreUnavailableError:
            logger.warning("Result store unavailable; device output returned without a handle")
        except ValueError:
            logger.info("Device output too large for one handle; returned without a handle")
        return None
