"""Parsing already-fetched device output with TextFSM or Genie (doc/AI_TOOL_CHAIN.md §43).

Injectable and free of database access (TextFSM runs in a killable child process, Genie through the
injected client). The text that is parsed is always the *redacted*
output the assistant already stores behind a handle, so a secret never reaches the Genie shim (an
external process). The result of every command has the shape the ``run-command`` step uses
(``{"parsed": ..., "error": ...}``) and a parse problem is an error on that one command, never an
exception for the whole call.

TextFSM here is ``ntc_templates`` (the same templates Netmiko uses for ``use_textfsm``); Genie goes
through the injected ``GenieParser`` (``genie_parser.DbGenieParser`` in production).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core import textfsm_isolated
from services.network.pyats.platform import UnsupportedPlatformError, resolve_pyats_os

PARSERS = ("textfsm", "genie")

# Fixed texts: they are shown to the user and to the model, so they never echo device output.
NO_TEXTFSM_TEMPLATE = "No TextFSM template exists for this command and device type"
NO_TEXTFSM_MATCH = "The output did not match the TextFSM template"
UNKNOWN_DEVICE_TYPE = "The device type is not known for this parser"
GENIE_NOT_AVAILABLE = "Genie parsing is not available"
PARSER_FAILED = "The parser failed on this output"
PARSER_TIMED_OUT = "The parser took too long on this output"

logger = logging.getLogger(__name__)


class ParserUnavailableError(Exception):
    """A parser cannot be used right now; the message is safe to show."""


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    parsed: Any | None
    error: str | None


class GenieParser(Protocol):
    async def parse(
        self, os_name: str, outputs: Sequence[tuple[str, str]]
    ) -> list[ParsedCommand]: ...

    async def learn_replay(
        self, os_name: str, feature: str, outputs: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """Genie's learned model (``{"info", "_exclude"}``) of ``feature`` from collected output."""
        ...

    async def diff_models(
        self, before: dict[str, Any], after: dict[str, Any], exclude: Sequence[str]
    ) -> dict[str, Any]:
        """Genie's diff of two learned models: ``{"identical", "diff", "excluded", ...}``."""
        ...


Span = tuple[int, int]


def valid_spans(text: str, commands: Sequence[str], spans: object) -> list[Span] | None:
    """``spans`` as a list of ``(start, end)`` pairs if it is a well-formed, ordered, in-range
    description of one output per command in ``text``; ``None`` otherwise (never guessed)."""
    if not isinstance(spans, list) or len(spans) != len(commands):
        return None
    result: list[Span] = []
    previous_end = 0
    for pair in spans:
        if (
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or not all(isinstance(n, int) and not isinstance(n, bool) for n in pair)
        ):
            return None
        start, end = pair
        if not previous_end <= start <= end <= len(text):
            return None
        result.append((start, end))
        previous_end = end
    return result


def slice_outputs(
    text: str, commands: Sequence[str], spans: Sequence[Span]
) -> list[tuple[str, str]]:
    """The ``(command, output)`` pairs of ``text``, cut at the offsets recorded when the output was
    captured. The device never chooses a boundary: a line in an output that looks like the next
    command's marker is just text inside that output (review finding 4)."""
    return [
        (command, text[start:end]) for command, (start, end) in zip(commands, spans, strict=True)
    ]


_TEXTFSM_ERRORS = {
    textfsm_isolated.NO_TEMPLATE: NO_TEXTFSM_TEMPLATE,
    textfsm_isolated.NO_MATCH: NO_TEXTFSM_MATCH,
    textfsm_isolated.TIMEOUT: PARSER_TIMED_OUT,
}


async def parse_textfsm(
    network_driver: str | None, outputs: Sequence[tuple[str, str]]
) -> list[ParsedCommand]:
    """TextFSM (``ntc_templates``) for each ``(command, output)``, in a killable child process."""
    if not network_driver:
        return [ParsedCommand(command, None, UNKNOWN_DEVICE_TYPE) for command, _ in outputs]
    outcome = await textfsm_isolated.run_textfsm(network_driver, outputs)
    if not outcome.ok:
        return [
            ParsedCommand(command, None, outcome.error or PARSER_FAILED) for command, _ in outputs
        ]
    return [
        ParsedCommand(command, item.rows, None)
        if item.error is None
        else ParsedCommand(command, None, _TEXTFSM_ERRORS.get(item.error, PARSER_FAILED))
        for (command, _), item in zip(outputs, outcome.items, strict=True)
    ]


async def parse_outputs(
    *,
    parser: str,
    outputs: Sequence[tuple[str, str]],
    network_driver: str | None,
    platform: str | None,
    genie: GenieParser | None,
) -> list[ParsedCommand]:
    """Parse every ``(command, output)`` with ``parser`` (``textfsm`` or ``genie``).

    Never raises for a parser problem: whatever goes wrong becomes a fixed-text error on every
    command, so a successful device run is never turned into a failure by its parse.
    """
    if parser not in PARSERS:
        raise ValueError(f"unknown parser: {parser!r}")
    if parser == "textfsm":
        return await parse_textfsm(network_driver or platform, outputs)
    if genie is None:
        return [ParsedCommand(command, None, GENIE_NOT_AVAILABLE) for command, _ in outputs]
    try:
        os_name = resolve_pyats_os(network_driver=network_driver, platform=platform)
    except UnsupportedPlatformError:
        return [ParsedCommand(command, None, UNKNOWN_DEVICE_TYPE) for command, _ in outputs]
    try:
        return await genie.parse(os_name, outputs)
    except ParserUnavailableError as exc:
        return [ParsedCommand(command, None, str(exc)) for command, _ in outputs]
    except Exception:  # the shim, the network or a malformed answer: fixed text, details in the log
        logger.warning("Genie parsing failed", exc_info=True)
        return [ParsedCommand(command, None, PARSER_FAILED) for command, _ in outputs]


def to_rows(entries: Sequence[ParsedCommand]) -> list[dict[str, Any]]:
    """Flat rows for the result store, so ``query_result`` and ``fetch_slice`` work on them.

    A TextFSM result is a list of dicts: each becomes a row with the command in ``_command``.
    Anything else (a Genie dict) is one row ``{"_command", "parsed"}`` per command; a command that
    did not parse is ``{"_command", "_error"}``. The underscore keeps the command column clear of
    the template's own column names.
    """
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if entry.error is not None:
            rows.append({"_command": entry.command, "_error": entry.error})
        elif isinstance(entry.parsed, list) and all(isinstance(r, dict) for r in entry.parsed):
            rows.extend({"_command": entry.command, **row} for row in entry.parsed)
        else:
            rows.append({"_command": entry.command, "parsed": entry.parsed})
    return rows
