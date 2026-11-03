"""The assistant's Genie client: the one configured pyATS source, used as the calling user (§43).

The text sent to the shim is the redacted output the assistant already stores, never a raw device
read. The permission ``sources.pyats:read`` is checked on every call (the seeded ``viewer`` role
does not hold it, so it has no Genie). With no source, or with several, Genie is unavailable and
the message says so; the assistant never picks one of several for the user.
"""

from __future__ import annotations

import asyncio
import logging
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
# The client waits at most this long for the shim, whatever the source's own timeout says.
SHIM_TIMEOUT_SECONDS = 60.0


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
        devices = {
            _DEVICE_KEY: {
                "os": os_name,
                "commands": [{"command": c, "output": o} for c, o in outputs],
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
        return [_entry(command, commands.get(command)) for command, _ in outputs]


def _commands_of(response: Any) -> dict[str, Any]:
    """The per-command answers of the shim's reply, or ``ParserUnavailableError`` if misshapen."""
    try:
        commands = response["results"][_DEVICE_KEY]["commands"]
    except (KeyError, TypeError) as exc:
        raise ParserUnavailableError(SHIM_FAILED) from exc
    if not isinstance(commands, dict):
        raise ParserUnavailableError(SHIM_FAILED)
    return commands


def _entry(command: str, answer: Any) -> ParsedCommand:
    if not isinstance(answer, dict):
        return ParsedCommand(command, None, NO_SHIM_RESULT)
    parsed = answer.get("parsed")
    if answer.get("error") or not isinstance(parsed, (dict, list)):
        return ParsedCommand(command, None, GENIE_COULD_NOT_PARSE)
    return ParsedCommand(command, parsed, None)
