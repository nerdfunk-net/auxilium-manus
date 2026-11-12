"""Wiki notes of the workflow open in the builder: one read and one proposal.

The notes are free text the user (or a colleague) wrote, so before the model sees them they are
redacted: credentials (patterns plus the exact values of the credentials the user can see) and,
unless the user shared addresses, IPv4 / IPv6 / MAC addresses. Both become restorable tokens, so
a proposal that keeps a token writes the original value back.

``propose_workflow_notes`` never saves. It hands the client a proposal; the user's click on
Save notes saves it through the ordinary notes endpoint, with the user's own permissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.workflows import MAX_NOTES_CHARS
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.knowledge_loader import load_knowledge
from services.ai_assistant.redaction import PLACEHOLDER_MARKER, Redactor
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

NOTES_EXTRAS_KEY = "workflow_notes"
# How much of the notes goes into the system prompt; the tool returns more.
MAX_PROMPT_NOTES_CHARS = 8000


class NotesReader(Protocol):
    async def read_notes(self, workflow_id: int) -> str | None: ...


@dataclass(frozen=True)
class WorkflowNotesState:
    workflow_id: int | None
    reader: NotesReader
    # False: the user's credential values could not be loaded, so exact-match redaction is not
    # available and the notes are not sent (fail closed).
    available: bool = True
    mask_addresses: bool = True


def notes_state(ctx: ToolContext) -> WorkflowNotesState:
    return ctx.extras[NOTES_EXTRAS_KEY]


_TOKEN = re.compile(r"__(?:SECRET|ADDR)_\d+__")
UNREADABLE_MESSAGE = (
    "The wiki of this workflow cannot be read (it no longer exists, is private to someone else, "
    "or you may not read it). Do not assume it is empty and do not try to write it."
)


def cut_notes(text: str, limit: int) -> tuple[str, bool]:
    """``text`` cut to at most ``limit`` characters at a line end and never inside a redaction
    token (a half token would be stored as plain text by a proposal built from it)."""
    if len(text) <= limit:
        return text, False
    end = limit
    for match in _TOKEN.finditer(text, max(0, limit - 20), limit + 20):
        if match.start() < limit < match.end():
            end = match.start()
            break
    newline = text.rfind("\n", 0, end)
    if newline > end // 2:
        end = newline
    return text[:end], True


def redact_notes(redactor: Redactor, notes: str, *, mask_addresses: bool) -> str:
    """Credentials first, then (unless shared) addresses; both restorable."""
    text = redactor.redact(notes)
    return redactor.redact_addresses(text) if mask_addresses else text


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposeNotesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(max_length=MAX_NOTES_CHARS, description="The COMPLETE new notes, Markdown")
    summary: str = Field(min_length=1, max_length=500)


async def _get_notes(ctx: ToolContext, args: NoInput) -> ToolOutput:
    state = notes_state(ctx)
    if state.workflow_id is None:
        return ToolOutput("The workflow is not saved yet, so it has no wiki notes.")
    if not state.available:
        return ToolOutput(_withheld_message())
    notes = await state.reader.read_notes(state.workflow_id)
    ctx.audit_refs.add(f"workflow_notes:{state.workflow_id}")
    if notes is None:
        return ToolOutput(UNREADABLE_MESSAGE, is_error=True)
    if notes == "":
        return ToolOutput("The workflow has no wiki notes yet.")
    return ToolOutput(redact_notes(ctx.redactor, notes, mask_addresses=state.mask_addresses))


def _withheld_message() -> str:
    marker = not_shared_marker(DataClass.CONTENT)
    return (
        f"The wiki notes are withheld ({marker['not_shared']}): credentials could not be checked."
    )


async def _propose_notes(ctx: ToolContext, args: ProposeNotesInput) -> ToolOutput:
    state = notes_state(ctx)
    if state.workflow_id is None:
        return ToolOutput(
            "Save the workflow first; an unsaved workflow has no wiki.", is_error=True
        )
    if not state.available:
        return ToolOutput(_withheld_message(), is_error=True)
    current = await state.reader.read_notes(state.workflow_id)
    if current is None:
        # No notes the user may read, or the workflow is gone.
        return ToolOutput(UNREADABLE_MESSAGE, is_error=True)
    restored = ctx.redactor.restore(args.notes)
    if Redactor.has_unresolved_token(restored) or PLACEHOLDER_MARKER in restored:
        return ToolOutput(
            "The notes contain a redaction token (__SECRET_n__ / __ADDR_n__) that does not come "
            "from the current notes, or a ***REDACTED*** marker. Keep tokens exactly where they "
            "are, or remove them, and propose again.",
            is_error=True,
        )
    if len(restored) > MAX_NOTES_CHARS:
        return ToolOutput(
            f"The notes may have at most {MAX_NOTES_CHARS} characters.", is_error=True
        )
    if restored == current:
        return ToolOutput("The proposed notes are identical to the current notes.", is_error=True)
    ctx.audit_refs.add(f"workflow_notes:{state.workflow_id}")

    warnings: list[str] = []
    if ctx.redactor.secret_values_in(restored) - ctx.redactor.secret_values_in(current):
        warnings.append(
            "The new text contains something that looks like a credential. Notes are readable by "
            "everyone who can open this workflow; check it before applying."
        )
    proposal = {
        "kind": "workflow_notes",
        "workflow_id": state.workflow_id,
        "summary": args.summary,
        "notes": restored,
        "base_notes": current,
        "warnings": warnings,
    }
    message = (
        "Proposal accepted and shown to the user with Save notes / Reject buttons. The notes are "
        "NOT saved until the user clicks Save notes; do not say they were. Briefly say what you "
        "changed."
    )
    return ToolOutput(message, proposal=proposal)


async def _get_template(ctx: ToolContext, args: NoInput) -> ToolOutput:
    return ToolOutput(load_knowledge("wiki_notes_template"))


GET_TEMPLATE_TOOL = Tool(
    "get_wiki_template",
    "The standard structure of a workflow wiki (Purpose, Assumptions / prerequisites, Gotchas, "
    "Example), how to fill each section from the canvas, and a finished example. Read it before "
    "you write or rewrite wiki notes.",
    NoInput,
    _get_template,
)

GET_NOTES_TOOL = Tool(
    "get_workflow_notes",
    "The wiki notes (Markdown) of the open workflow: its purpose, assumptions and hints. Secrets "
    "and, unless shared, addresses appear as __SECRET_n__ / __ADDR_n__ tokens.",
    NoInput,
    _get_notes,
)

PROPOSE_NOTES_TOOL = Tool(
    "propose_workflow_notes",
    "Propose the COMPLETE new wiki notes of the open workflow (not a diff), keeping every token "
    "you want to keep. It is shown to the user as a diff; nothing is saved until they click "
    "Save notes.",
    ProposeNotesInput,
    _propose_notes,
)
