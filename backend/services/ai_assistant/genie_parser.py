"""The assistant's Genie client: the one configured pyATS source, used as the calling user (§43).

The text sent to the shim is the redacted output the assistant already stores, never a raw device
read. The permission ``sources.pyats:read`` is checked on every call (the seeded ``viewer`` role
does not hold it, so it has no Genie). With no source, or with several, Genie is unavailable and
the message says so; the assistant never picks one of several for the user.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any

import service_factory
from core.database import SessionLocal
from services.ai_assistant.output_parser import ParsedCommand, ParserUnavailableError
from services.auth.rbac_service import RBACService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)

logger = logging.getLogger(__name__)

# The shim reads one "device" per call; the key is only a label inside the request.
_DEVICE_KEY = "device"

NOT_ALLOWED = "You are not allowed to use the pyATS source"
NO_SOURCE = "No pyATS source is configured, so Genie cannot be used"
SEVERAL_SOURCES = "There is more than one pyATS source; ask an administrator to keep one for Genie"
SHIM_FAILED = "The pyATS service could not parse the output"
NO_SHIM_RESULT = "The pyATS service returned nothing for this command"
# The shim reports ``str(exception)`` per command; that text is never passed on (it can quote CLI
# output), only this fixed sentence (review finding 5).
GENIE_COULD_NOT_PARSE = "Genie could not parse this output"
# A command that printed nothing (a feature that is not configured) is not a parse failure; it is
# not sent to the shim.
NO_OUTPUT = "No output (nothing is configured for this command)"
# Lines a device prints when a feature is not configured. Genie has no parser for them, so it fails;
# when EVERY line of a failed output is one of these, the failure is "nothing configured", not a
# parse error. Anything else stays "could not parse".
NOT_CONFIGURED = "The device reports that nothing is configured for this command"
_NOT_CONFIGURED_LINES = (
    re.compile(r"no templates configured", re.IGNORECASE),
    re.compile(r"for address family: .+", re.IGNORECASE),
    re.compile(r"% dampening not enabled.*", re.IGNORECASE),
    # ``show bgp all cluster-ids`` with no cluster id: the column header only.
    re.compile(r"cluster-id\s+#-neighbors\s+C2C-rfl-CFG\s+C2C-rfl-USE", re.IGNORECASE),
)


_TOTAL_PREFIXES = re.compile(r"Total number of prefixes\s+(\d+)", re.IGNORECASE)
_MATCHING_LINES = re.compile(r"Number of lines which match regexp\s*=\s*(\d+)", re.IGNORECASE)
_TOTAL_FILTERS = ("| include total number of prefixes", "| count")
NO_TOTAL = (
    "The device printed no total (no routes, or the command is not supported here); "
    "read the raw text"
)


def filtered_total(command: str, output: str) -> ParsedCommand | None:
    """The parsed total of a route list read with the prefix-total or count filter.

    Genie has no parser for these commands, so they are read here and never sent to the shim.
    ``None`` when ``command`` is not such a command.
    """
    if not command.strip().lower().endswith(_TOTAL_FILTERS):
        return None
    if match := _TOTAL_PREFIXES.search(output):
        return ParsedCommand(command, {"total_prefixes": int(match.group(1))}, None)
    if match := _MATCHING_LINES.search(output):
        return ParsedCommand(command, {"matching_lines": int(match.group(1))}, None)
    return ParsedCommand(command, None, NO_TOTAL)


def nothing_configured(output: str) -> bool:
    """Whether ``output`` consists only of "feature not configured" lines."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return bool(lines) and all(
        any(pattern.fullmatch(line) for pattern in _NOT_CONFIGURED_LINES) for line in lines
    )


# The client waits at most this long for the shim, whatever the source's own timeout says.
SHIM_TIMEOUT_SECONDS = 60.0
# Learning a feature from replayed output starts a mock device in the shim (about 15 s) per call.
LEARN_TIMEOUT_SECONDS = 120.0
LEARN_FAILED = "Genie could not learn the feature from this output"


def _single_source_id(db: Any, user_id: int) -> str:
    """The id of the one pyATS source, or ``ParserUnavailableError`` (message safe to show)."""
    if not RBACService(db).has_permission(user_id, "sources.pyats", "read"):
        raise ParserUnavailableError(NOT_ALLOWED)
    sources = PyATSSourceConfigService(db).list_sources()
    if not sources:
        raise ParserUnavailableError(NO_SOURCE)
    if len(sources) > 1:
        raise ParserUnavailableError(SEVERAL_SOURCES)
    return str(sources[0]["source_id"])


def has_pyats_source(user_id: int) -> bool:
    """Whether Genie can be offered to this user: allowed, and exactly one source exists."""
    with SessionLocal() as db:
        try:
            _single_source_id(db, user_id)
        except ParserUnavailableError:
            return False
    return True


def _credentials(user_id: int) -> Any:
    with SessionLocal() as db:
        source_id = _single_source_id(db, user_id)
        try:
            return PyATSSourceConfigService(db).resolve_credentials(source_id)
        except (PyATSSourceNotFoundError, PyATSValidationError) as exc:
            logger.info("AI assistant: pyATS source unusable")
            raise ParserUnavailableError(SHIM_FAILED) from exc


class DbGenieParser:
    """Implements ``output_parser.GenieParser`` with the pyATS shim."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def parse(self, os_name: str, outputs: Sequence[tuple[str, str]]) -> list[ParsedCommand]:
        credentials = await asyncio.to_thread(_credentials, self._user_id)
        local = {c: filtered_total(c, o) for c, o in outputs}
        to_parse = [(c, o) for c, o in outputs if o.strip() and local[c] is None]
        if not to_parse:
            return [local[c] or ParsedCommand(c, None, NO_OUTPUT) for c, _ in outputs]
        devices = {
            _DEVICE_KEY: {
                "os": os_name,
                "commands": [{"command": c, "output": o} for c, o in to_parse],
            }
        }
        try:
            response = await service_factory.get_pyats_app_service().parse_batch(
                credentials, devices=devices, timeout_seconds=SHIM_TIMEOUT_SECONDS
            )
        except (PyATSValidationError, PyATSAPIError) as exc:
            logger.info("AI assistant: pyATS parse failed (%s)", type(exc).__name__)
            raise ParserUnavailableError(SHIM_FAILED) from exc
        except ValueError as exc:  # a 200 whose body is not JSON
            logger.info("AI assistant: pyATS parse answer was not JSON")
            raise ParserUnavailableError(SHIM_FAILED) from exc
        commands = _commands_of(response)
        return [
            local[command] or _entry(command, commands.get(command), output)
            for command, output in outputs
        ]

    async def learn_replay(
        self, os_name: str, feature: str, outputs: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """The learned model from collected output, or ``ParserUnavailableError`` (safe text)."""
        credentials = await asyncio.to_thread(_credentials, self._user_id)
        commands = [{"command": c, "output": o} for c, o in outputs]
        try:
            answer = await service_factory.get_pyats_app_service().learn_replay(
                credentials,
                os_name=os_name,
                feature=feature,
                commands=commands,
                timeout_seconds=LEARN_TIMEOUT_SECONDS,
            )
        except (PyATSValidationError, PyATSAPIError) as exc:
            logger.info("AI assistant: pyATS learn failed (%s)", type(exc).__name__)
            raise ParserUnavailableError(SHIM_FAILED) from exc
        except ValueError as exc:
            raise ParserUnavailableError(SHIM_FAILED) from exc
        payload = answer.get("payload") if isinstance(answer, dict) else None
        if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
            # The shim's own sentence is fixed text (no CLI output in it), but say only ours.
            raise ParserUnavailableError(LEARN_FAILED)
        return payload

    async def diff_models(
        self, before: dict[str, Any], after: dict[str, Any], exclude: Sequence[str]
    ) -> dict[str, Any]:
        credentials = await asyncio.to_thread(_credentials, self._user_id)
        try:
            answer = await service_factory.get_pyats_app_service().diff(
                credentials,
                snapshot_a=before,
                snapshot_b=after,
                exclude_keys=list(exclude),
                timeout_seconds=SHIM_TIMEOUT_SECONDS,
            )
        except (PyATSValidationError, PyATSAPIError) as exc:
            logger.info("AI assistant: pyATS diff failed (%s)", type(exc).__name__)
            raise ParserUnavailableError(SHIM_FAILED) from exc
        except ValueError as exc:
            raise ParserUnavailableError(SHIM_FAILED) from exc
        if not isinstance(answer, dict) or "identical" not in answer:
            raise ParserUnavailableError(SHIM_FAILED)
        return answer


def _commands_of(response: Any) -> dict[str, Any]:
    """The per-command answers of the shim's reply, or ``ParserUnavailableError`` if misshapen."""
    try:
        commands = response["results"][_DEVICE_KEY]["commands"]
    except (KeyError, TypeError) as exc:
        raise ParserUnavailableError(SHIM_FAILED) from exc
    if not isinstance(commands, dict):
        raise ParserUnavailableError(SHIM_FAILED)
    return commands


def _entry(command: str, answer: Any, output: str) -> ParsedCommand:
    if not output.strip():
        return ParsedCommand(command, None, NO_OUTPUT)
    if not isinstance(answer, dict):
        return ParsedCommand(command, None, NO_SHIM_RESULT)
    parsed = answer.get("parsed")
    if answer.get("error") or not isinstance(parsed, (dict, list)):
        if nothing_configured(output):
            return ParsedCommand(command, None, NOT_CONFIGURED)
        return ParsedCommand(command, None, GENIE_COULD_NOT_PARSE)
    return ParsedCommand(command, parsed, None)
