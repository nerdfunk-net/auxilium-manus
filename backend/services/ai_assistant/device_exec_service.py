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
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from services.ai_assistant.audit import log_device_command
from services.ai_assistant.command_policy import (
    MAX_COMMANDS,
    MAX_SIGNED_COMMANDS,
    check_commands,
    is_probe_run,
)
from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.device_access import (
    DEVICE_DRIVERS,
    LONG_READ_TIMEOUT_SECONDS,
    DeviceCommandOutput,
    DeviceCommandRunner,
    DeviceResolver,
    driver_known,
    long_command_count,
)
from services.ai_assistant.device_token import (
    DeviceCommandGrant,
    InvalidTokenError,
    verify_token,
)
from services.ai_assistant.genie_parser import DbGenieParser
from services.ai_assistant.known_secrets import try_load_visible_secret_values
from services.ai_assistant.learn import catalogue as learn_catalogue
from services.ai_assistant.output_parser import GenieParser
from services.ai_assistant.parse_service import ParseOutcome, parse_stored_text
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
# The whole run (connect, every command, disconnect) may take this long for up to five commands;
# Netmiko's own timeouts are per command. A longer catalogue plan (feature learn) gets
# ``EXTRA_SECONDS_PER_COMMAND`` for each command beyond five.
RUN_TIMEOUT_SECONDS = 300
EXTRA_SECONDS_PER_COMMAND = 20
# A run of long-read commands (BGP tables, databases) may take up to this long in all.
MAX_RUN_TIMEOUT_SECONDS = 600
CONNECT_SLACK_SECONDS = 60
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
    # The parser the user was shown (§43). The raw output above is kept in every case.
    parser: str = "none"
    parsed_handle: str | None = None
    parsed_text: str = ""
    # (command, why it was not parsed) for each command that failed to parse
    parse_errors: tuple[tuple[str, str], ...] = ()


def _cut(text: str, limit: int) -> str:
    """The first ``limit`` characters, ending on a line boundary when one is near the end."""
    head = text[:limit]
    newline = head.rfind("\n")
    return head[:newline] if newline > limit // 2 else head


def run_budget_seconds(command_count: int, long_count: int = 0) -> float:
    """The time one run may take.

    The base budget plus a little for each command beyond five, but never less than every
    long-read command needs at its own read timeout (plus connect time), so the whole run does not
    time out while a command is still inside its read timeout and the output already collected is
    thrown away. Capped at ``MAX_RUN_TIMEOUT_SECONDS``.
    """
    extra = max(0, command_count - MAX_COMMANDS) * EXTRA_SECONDS_PER_COMMAND
    needed = long_count * LONG_READ_TIMEOUT_SECONDS + CONNECT_SLACK_SECONDS
    return min(max(RUN_TIMEOUT_SECONDS + extra, needed), MAX_RUN_TIMEOUT_SECONDS)


def _shape_blocks(
    outputs: Sequence[tuple[str, str]], redact: Callable[[str], str]
) -> tuple[str, bool, list[list[int]]]:
    """The stored text (``$ command`` blocks joined by a blank line), whether it was cut, and the
    ``[start, end]`` offsets of each command's output in that text.

    Redact first, cut second: a secret that straddles the cut is already gone. Every output is
    redacted on its own, so its offsets are known exactly in the final text; later parsing cuts
    at those offsets and never searches the device's text for a boundary (review finding 4).
    Output beyond ``MAX_RAW_CHARS`` (all commands together) is cut before redaction on a line
    boundary (the redactor has a budget); the text is then cut to the shown size.
    """
    parts: list[str] = []
    spans: list[list[int]] = []
    position = 0
    truncated = False
    budget = MAX_RAW_CHARS
    for command, raw in outputs:
        body = raw.rstrip()
        if len(body) > budget:
            body = _cut(body, budget)
            truncated = True
        budget -= len(body)
        redacted = redact(body) if body else ""
        header = f"$ {command}\n"
        if parts:
            position += 2  # the blank line between blocks
        start = position + len(header)
        spans.append([start, start + len(redacted)])
        parts.append(f"{header}{redacted}")
        position = start + len(redacted)
    text = "\n\n".join(parts)
    if len(text) > MAX_OUTPUT_CHARS:
        shown = _cut(text, MAX_OUTPUT_CHARS)
        spans = [[min(start, len(shown)), min(end, len(shown))] for start, end in spans]
        text = (
            f"{shown}\n…[output truncated: showed {len(shown)} of {len(text)} characters; "
            "the rest was left out]"
        )
        truncated = True
    return text, truncated, spans


class DeviceCommandExecutor:
    def __init__(
        self,
        resolver: DeviceResolver,
        runner: DeviceCommandRunner,
        store: ResultStore | None,
        *,
        secret_loader: Callable[[int], list[str] | None] = try_load_visible_secret_values,
        genie_factory: Callable[[int], GenieParser | None] = DbGenieParser,
    ) -> None:
        self._resolver = resolver
        self._runner = runner
        self._store = store
        self._secret_loader = secret_loader
        self._genie_factory = genie_factory

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
        # More than the free-form limit is allowed only for a reviewed catalogue plan.
        limit = MAX_SIGNED_COMMANDS if learn_catalogue.is_plan(grant.commands) else MAX_COMMANDS
        commands = check_commands(list(grant.commands), limit=limit, allow_probes=True)
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
        budget = run_budget_seconds(len(commands), long_command_count(commands))
        try:
            raw = await asyncio.wait_for(
                self._runner.run(
                    device,
                    commands,
                    credential_id=credential_id,
                    user_id=user_id,
                    network_driver=chosen_driver,
                ),
                timeout=budget,
            )
        except TimeoutError:
            raw = DeviceCommandOutput(
                False, f"The device did not finish within {budget:g} seconds", ()
            )
        redactor = Redactor(max_chars=MAX_RAW_CHARS + _REDACT_SLACK)
        redactor.add_known_secrets(secrets)
        output, truncated, spans = await asyncio.to_thread(
            _shape_blocks, list(raw.outputs), redactor.redact
        )
        # Redact a generous prefix, then show the first MAX_ERROR_CHARS of it: a cut at the prefix
        # boundary is far beyond the part that is shown.
        error = (
            redactor.redact(raw.error[:MAX_ERROR_RAW_CHARS])[:MAX_ERROR_CHARS]
            if raw.error
            else None
        )
        handle = None
        meta = {
            # What a later parse needs, from the capture itself (not from the device's text).
            "commands": [command for command, _ in raw.outputs],
            "spans": spans,
            "parser": grant.parser,
            "network_driver": chosen_driver or device.network_driver,
            "platform": device.platform,
            # Which device the output came from, so a later tool compares it with that device's
            # documentation and not with one the model names (doc/AI_TOOL_CHAIN.md §45).
            "device_name": device.name,
            # The stable identity of the device (the name is only a label): two readings are of
            # one router only when these match (``compare_bgp_learns``).
            "device_id": device.device_id,
            "source_id": device.source_id,
        }
        # A probe run that failed (a traceroute hit the read timeout after the ping finished) still
        # keeps what finished, so the assistant can report the ping; a failed show run keeps none
        # because half a config would read as a whole one.
        if output and (raw.success or is_probe_run(commands)):
            handle = await self._store_output(user_id, output, meta, truncated)
        parsed = await self._parse(
            user_id,
            grant.parser,
            raw.success and bool(output),
            output,
            raw.outputs,
            spans,
            meta,
            handle,
            truncated,
        )
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
            parser=grant.parser,
            parsed_handle=parsed.handle if parsed else None,
            parsed_text=parsed.text if parsed else "",
            parse_errors=tuple((e.command, e.error) for e in parsed.entries if e.error)
            if parsed
            else (),
        )

    async def _parse(
        self,
        user_id: int,
        parser: str,
        has_output: bool,
        output: str,
        outputs: Sequence[tuple[str, str]],
        spans: list[list[int]],
        meta: dict[str, object],
        source_handle: str | None,
        truncated: bool,
    ) -> ParseOutcome | None:
        """Parse the *redacted* output the user is shown, never the raw text (Genie is external)."""
        if parser == "none" or not has_output:
            return None
        genie = self._build_genie(user_id) if parser == "genie" else None
        return await parse_stored_text(
            user_id=user_id,
            store=self._store,
            parser=parser,
            text=output,
            commands=[command for command, _ in outputs],
            spans=spans,
            network_driver=str(meta["network_driver"]) if meta["network_driver"] else None,
            platform=str(meta["platform"]) if meta["platform"] else None,
            genie=genie,
            source_handle=source_handle,
            partial=truncated,
        )

    def _build_genie(self, user_id: int) -> GenieParser | None:
        """The Genie client, or ``None`` (reported as "not available") if it cannot be built:
        a parse problem must never turn a device run that succeeded into a failure."""
        try:
            return self._genie_factory(user_id)
        except Exception:
            logger.warning("Could not build the Genie parser", exc_info=True)
            return None

    async def _store_output(
        self, user_id: int, output: str, meta: dict[str, object], truncated: bool
    ) -> str | None:
        if self._store is None:
            return None
        try:
            return await self._store.put(
                user_id,
                StoredResult(
                    kind=HANDLE_KIND,
                    data_class=DataClass.CONTENT,
                    text=output,
                    partial=truncated,
                    meta=meta,
                ),
            )
        except ResultStoreUnavailableError:
            logger.warning("Result store unavailable; device output returned without a handle")
        except ValueError:
            logger.info("Device output too large for one handle; returned without a handle")
        return None
