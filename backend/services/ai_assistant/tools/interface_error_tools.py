"""``summarize_interface_errors``: which interfaces have error or drop counters (§54).

A pure read of the parsed rows of ``show interfaces`` (the ``parsed_output`` handle a TextFSM run
leaves). The server does the counting, so a device with hundreds of interfaces costs the model the
same as one with a few: it sees at most one preview of the interfaces that have a problem, never
the rows. It reads the handle as the calling user and checks the content opt-in on every call.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.interface_errors import (
    ALL_COUNTERS,
    ErrorSummary,
    is_interface_row,
    summarize_interface_errors,
)
from services.ai_assistant.parse_service import PARSED_KIND
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.result_publish import publish_table
from services.ai_assistant.tools.result_tools import HANDLE_FIELD, load_stored_result

# The kind of the table of interfaces with a problem that goes behind a handle.
FINDINGS_KIND = "interface_errors"
MAX_COLUMNS_SHOWN = 60

_NOT_PARSED_ROWS = (
    "This handle does not hold parsed rows. Run 'show interfaces' with propose_device_command and "
    "parser 'textfsm', or call parse_command_output(handle, 'textfsm') on the stored output, and "
    "use the parsed handle."
)
_NO_INTERFACE_ROWS = (
    "The parsed rows have no interface rows (a column 'interface'): the command did not parse, or "
    "it was not 'show interfaces'. Run 'show interfaces' with parser 'textfsm'."
)
_CUMULATIVE = (
    "The counters are cumulative since the interface counters were last cleared (or the device "
    "booted): a non-zero value does not mean the problem is still happening. Say so, and use "
    "rates_percent to judge how much traffic is affected."
)
_PARTIAL_NOTE = (
    "The stored output was cut for size, so interfaces at the end of it may be missing and this "
    "answer may be incomplete. Say so in the answer and do not call the device clean."
)
_UNPARSED_NOTE = (
    "Another command in the same output did not parse, so the output is not fully checked. Say so "
    "and do not call the device clean."
)
_NO_DROPS_NOTE = (
    "The template of this platform has no drop counters, so drops were NOT checked: do not say "
    "there are no drops."
)
_NO_ERRORS_NOTE = (
    "The template of this platform has no error counters, so errors were NOT checked: do not say "
    "there are no errors."
)
MAX_CLASH_NAMES = 10


class SummarizeInterfaceErrorsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = HANDLE_FIELD
    interface: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Only this interface (full name or abbreviation such as 'Gi0/1'); omit it to check "
            "every interface of the device. It is reported even when it has no errors."
        ),
    )


def _summary_dict(summary: ErrorSummary, *, filtered: bool, complete: bool) -> dict[str, Any]:
    return {
        "interfaces_in_output": summary.interfaces_in_output,
        "interfaces_checked": summary.interfaces_checked,
        "interfaces_with_problems": summary.interfaces_with_problems,
        "interfaces_with_errors": summary.interfaces_with_errors,
        "interfaces_with_drops": summary.interfaces_with_drops,
        # Clean only when nothing is wrong AND everything was seen: a cut output, or a command of
        # it that did not parse, can hide the interface that has the errors.
        "complete": complete,
        "clean": summary.interfaces_with_problems == 0 and complete,
        "errors_checked": summary.errors_checked,
        "drops_checked": summary.drops_checked,
        "counter_totals": summary.counter_totals,
        "counters_looked_at": list(summary.counters_looked_at),
        "counters_not_in_output": list(summary.counters_not_in_output),
        "unparsed_commands": summary.unparsed,
        "rows_are": "the checked interfaces" if filtered else "interfaces with a problem",
    }


async def _summarize_interface_errors(
    ctx: ToolContext, args: SummarizeInterfaceErrorsInput
) -> ToolOutput:
    loaded = await load_stored_result(ctx, args.handle)
    if isinstance(loaded, ToolOutput):
        return loaded
    if loaded.kind != PARSED_KIND or loaded.rows is None:
        return ToolOutput(_NOT_PARSED_ROWS, is_error=True)
    rows = loaded.rows
    if not any(is_interface_row(r) for r in rows):
        return ToolOutput(_NO_INTERFACE_ROWS, is_error=True)
    summary = summarize_interface_errors(rows, interface=args.interface)
    if summary.ambiguous:
        names = ", ".join(summary.ambiguous[:MAX_CLASH_NAMES])
        return ToolOutput(
            f"That name fits more than one type of interface ({names}). Ask the user, or pass "
            "the full interface name.",
            is_error=True,
        )
    if args.interface is not None and summary.interfaces_checked == 0:
        return ToolOutput(
            f"No interface in the output matches that name. The output has "
            f"{summary.interfaces_in_output} interfaces; check the name or omit 'interface'.",
            is_error=True,
        )
    if not summary.counters_looked_at:
        columns = sorted({str(k) for r in rows if is_interface_row(r) for k in r})
        return ToolOutput(
            "None of the error or drop counters this tool knows "
            f"({', '.join(ALL_COUNTERS)}) is in the parsed rows, so nothing can be said about "
            "errors. The template of this platform has the columns: "
            f"{', '.join(columns[:MAX_COLUMNS_SHOWN])}.",
            is_error=True,
        )
    complete = not loaded.partial and summary.unparsed == 0
    notes = [_CUMULATIVE]
    if loaded.partial:
        notes.append(_PARTIAL_NOTE)
    if summary.unparsed:
        notes.append(_UNPARSED_NOTE)
    if not summary.drops_checked:
        notes.append(_NO_DROPS_NOTE)
    if not summary.errors_checked:
        notes.append(_NO_ERRORS_NOTE)
    note = " ".join(notes)
    return await publish_table(
        ctx,
        [dict(f) for f in summary.findings],
        kind=FINDINGS_KIND,
        data_class=DataClass.CONTENT,
        source_truncated=loaded.partial,
        note=note,
        extra={
            "summary": _summary_dict(
                summary, filtered=args.interface is not None, complete=complete
            )
        },
    )


_DESCRIPTION = (
    "Which interfaces of a device have errors or drops, from the parsed rows of 'show interfaces' "
    "(the parsed handle of a confirmed propose_device_command run with parser 'textfsm'). Use it "
    'for "do you see interface errors on X"; do NOT page through the parsed rows yourself, this '
    "tool counts them on the server and returns only the interfaces that have a non-zero counter "
    "(input_errors, output_errors, crc, frame, overrun, abort, runts, giants, queue_drops, "
    "queue_output_drops and the NX-OS stomped_crc, short_frame, discards), worst first, with the "
    "packet counts and the error rate. 'summary' says how many interfaces were checked, how many "
    "have a problem and whether the device is clean: 'clean' is true only when 'complete' is too "
    "(the output was not cut and every command parsed). Nothing is run on the device."
)


def build_interface_error_tools() -> list[Tool]:
    return [
        Tool(
            "summarize_interface_errors",
            _DESCRIPTION,
            SummarizeInterfaceErrorsInput,
            _summarize_interface_errors,
        )
    ]
