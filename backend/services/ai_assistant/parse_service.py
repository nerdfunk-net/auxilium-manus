"""Split a stored device output, parse it, store the rows (doc/AI_TOOL_CHAIN.md §43).

Shared by the confirm-time executor (after a run with a parser) and the ``parse_command_output``
tool (on a handle). The text is the redacted text the assistant already stores, so nothing here
needs to scrub it again before it goes to TextFSM or the Genie shim.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.output_parser import (
    PARSER_FAILED,
    GenieParser,
    ParsedCommand,
    parse_outputs,
    slice_outputs,
    to_rows,
    valid_spans,
)
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)

logger = logging.getLogger(__name__)

PARSED_KIND = "parsed_output"
# Parsing may include a call to the pyATS shim; the whole parse is bounded here.
PARSE_TIMEOUT_SECONDS: float = 120
PARSE_TIMED_OUT = "Parsing took too long"
# The part of the parsed data shown on the card; the full rows stay behind the handle.
MAX_SHOWN_CHARS = 100_000


BAD_SPANS = "The stored output has no usable command boundaries"


@dataclass(frozen=True)
class ParseOutcome:
    entries: tuple[ParsedCommand, ...]
    handle: str | None
    text: str
    # True when the text that was parsed was itself cut: the rows are then a prefix.
    partial: bool = False


def render_text(entries: Sequence[ParsedCommand]) -> str:
    """The parsed data as indented JSON, cut to ``MAX_SHOWN_CHARS`` on a line boundary."""
    shown = [{"command": e.command, "parsed": e.parsed, "error": e.error} for e in entries]
    text = json.dumps(shown, indent=2, default=str, ensure_ascii=False)
    if len(text) <= MAX_SHOWN_CHARS:
        return text
    head = text[:MAX_SHOWN_CHARS]
    head = head[: head.rfind("\n")] if "\n" in head else head
    return (
        f"{head}\n…[cut: showed {len(head)} of {len(text)} characters; the rest is in the handle]"
    )


async def parse_stored_text(
    *,
    user_id: int,
    store: ResultStore | None,
    parser: str,
    text: str,
    commands: Sequence[str],
    spans: object,
    network_driver: str | None,
    platform: str | None,
    genie: GenieParser | None,
    source_handle: str | None,
    partial: bool = False,
    only_command: str | None = None,
) -> ParseOutcome:
    """Parse the per-command outputs of ``text``; store the rows when at least one parsed.

    ``spans`` are the ``(start, end)`` offsets of each command's output in ``text`` recorded when
    the output was captured, so the device's own text never decides where a command ends.
    ``only_command`` limits the parse to one of the commands. ``partial`` says the text was cut.
    """
    checked = valid_spans(text, commands, spans)
    if checked is None:
        entries = [ParsedCommand(command, None, BAD_SPANS) for command in commands]
        return ParseOutcome(entries=tuple(entries), handle=None, text=render_text(entries))
    outputs = slice_outputs(text, commands, checked)
    if only_command is not None:
        outputs = [pair for pair in outputs if pair[0] == only_command]
    try:
        entries = await asyncio.wait_for(
            parse_outputs(
                parser=parser,
                outputs=outputs,
                network_driver=network_driver,
                platform=platform,
                genie=genie,
            ),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        entries = [ParsedCommand(command, None, PARSE_TIMED_OUT) for command, _ in outputs]
    except Exception:  # a parse problem must never fail a run that already succeeded
        logger.warning("Parsing a device output failed unexpectedly", exc_info=True)
        entries = [ParsedCommand(command, None, PARSER_FAILED) for command, _ in outputs]
    handle = None
    if any(entry.error is None for entry in entries):
        handle = await _store_rows(user_id, store, parser, entries, source_handle, partial)
    return ParseOutcome(
        entries=tuple(entries), handle=handle, text=render_text(entries), partial=partial
    )


async def _store_rows(
    user_id: int,
    store: ResultStore | None,
    parser: str,
    entries: Sequence[ParsedCommand],
    source_handle: str | None,
    partial: bool,
) -> str | None:
    if store is None:
        return None
    meta = {"parser": parser, "source_handle": source_handle}
    try:
        return await store.put(
            user_id,
            StoredResult(
                kind=PARSED_KIND,
                data_class=DataClass.CONTENT,
                rows=to_rows(entries),
                partial=partial,
                meta=meta,
            ),
        )
    except ResultStoreUnavailableError:
        logger.warning("Result store unavailable; parsed output returned without a handle")
    except ValueError:
        logger.info("Parsed output too large for one handle; returned without a handle")
    return None
