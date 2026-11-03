"""``parse_command_output``: parse a stored device output with TextFSM or Genie (§43).

A pure read of a result the user already ran and stored: it cannot reach a device. It reads the
handle as the calling user, checks the content opt-in on every call, parses the redacted text and
stores the rows behind a new handle, so ``query_result`` and ``fetch_slice`` work on them. Genie
sends the (redacted) text to the pyATS shim; it is offered only when the session has a Genie parser.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from models.ai_assistant import DeviceDriver
from services.ai_assistant.output_parser import GenieParser, to_rows
from services.ai_assistant.parse_service import parse_stored_text
from services.ai_assistant.results.store import ResultStore
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.device_tools import GENIE_PARSER_KEY
from services.ai_assistant.tools.envelope import build_envelope, envelope_output, redact_envelope
from services.ai_assistant.tools.result_tools import (
    HANDLE_FIELD,
    RESULT_STORE_KEY,
    load_stored_result,
)

_GENIE_NOT_APPROVED = (
    "The user did not approve sending this output to the pyATS service for Genie. Use 'textfsm', "
    "or propose the command again with parser 'genie' so the user can confirm it."
)
_PARTIAL_NOTE = (
    "The stored output was cut for size, so these rows may be incomplete: later lines or whole "
    "commands may be missing. Say so in the answer."
)
_NOT_A_DEVICE_OUTPUT = (
    "Only the output of a device command can be parsed, and this handle is not one (or it was "
    "stored before parsing was possible). Run the command again with propose_device_command."
)


class ParseCommandOutputInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = HANDLE_FIELD
    parser: Literal["textfsm", "genie"] = Field(
        description="'textfsm' (ntc-templates templates) or 'genie' (pyATS, when it is available)"
    )
    command: str | None = Field(
        default=None,
        max_length=200,
        description="Parse only this command of the output; omit it to parse all of them",
    )
    network_driver: DeviceDriver | None = Field(
        default=None,
        description=(
            "Device type, only for an output whose device type was not stored with it; "
            "the stored one always wins"
        ),
    )


async def _parse_command_output(ctx: ToolContext, args: ParseCommandOutputInput) -> ToolOutput:
    loaded = await load_stored_result(ctx, args.handle)
    if isinstance(loaded, ToolOutput):
        return loaded
    meta = loaded.meta or {}
    commands = meta.get("commands")
    if (
        loaded.kind != "device_command"
        or loaded.text is None
        or not isinstance(commands, list)
        or "spans" not in meta
    ):
        return ToolOutput(_NOT_A_DEVICE_OUTPUT, is_error=True)
    names = [str(c) for c in commands]
    if args.command is not None and args.command not in names:
        return ToolOutput(
            f"That command is not in this output. The commands are: {', '.join(names)}.",
            is_error=True,
        )
    genie: GenieParser | None = ctx.extras.get(GENIE_PARSER_KEY)
    if args.parser == "genie" and genie is None:
        return ToolOutput(
            "Genie is not available (no single pyATS source the user may use). Use 'textfsm'.",
            is_error=True,
        )
    if args.parser == "genie" and meta.get("parser") != "genie":
        # Genie sends the stored text to the pyATS service. The user saw that on the card only for
        # a command proposed with Genie, so any other output needs a new proposal (finding 6).
        return ToolOutput(_GENIE_NOT_APPROVED, is_error=True)
    stored_driver = meta.get("network_driver")
    store: ResultStore = ctx.extras[RESULT_STORE_KEY]
    outcome = await parse_stored_text(
        user_id=ctx.user_id,
        store=store,
        parser=args.parser,
        text=loaded.text,
        commands=names,
        spans=meta.get("spans"),
        partial=loaded.partial,
        network_driver=str(stored_driver) if stored_driver else args.network_driver,
        platform=str(meta["platform"]) if meta.get("platform") else None,
        genie=genie,
        source_handle=args.handle,
        only_command=args.command,
    )
    ctx.audit_refs.add(f"result:{args.handle}")
    envelope = build_envelope(to_rows(outcome.entries))
    if outcome.handle is not None:
        envelope = envelope.with_handle(outcome.handle)
    if loaded.partial:
        envelope = envelope.with_note(_PARTIAL_NOTE)
    envelope = await asyncio.to_thread(redact_envelope, envelope, ctx.redactor)
    extra: dict[str, Any] = {
        "parser": args.parser,
        "errors": [{"command": e.command, "error": e.error} for e in outcome.entries if e.error],
    }
    return envelope_output(envelope, extra=extra)


_DESCRIPTION = (
    "Parse the stored output of a device command (the handle of a confirmed "
    "propose_device_command run) into structured rows with TextFSM or Genie. Use it for "
    "questions about values in 'show version', 'show ip interface brief' and similar output. "
    "Nothing is run on the device. The rows carry the command in '_command' and come with a "
    "handle for query_result / fetch_slice; a command with no template or no match is listed "
    "under 'errors'."
)


def build_output_parse_tools() -> list[Tool]:
    return [
        Tool(
            "parse_command_output",
            _DESCRIPTION,
            ParseCommandOutputInput,
            _parse_command_output,
        )
    ]
