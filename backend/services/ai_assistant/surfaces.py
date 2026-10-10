"""Per-surface assembly: which tools a chat turn gets and what the model is told up front.

Surfaces send their *current* client-side state; the server decides what of it the model may see
(doc/ai_integration/AI_ASSISTANT.md §9b) and redacts it before building the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.ai_assistant import TemplateEditorContext
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT, TEMPLATE_EDITOR_PROMPT
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.template_tools import (
    TEMPLATE_EDITOR_TOOLS,
    TemplateEditorState,
    TemplateReader,
)

MAX_VARIABLE_VALUE_CHARS = 1000


@dataclass(frozen=True)
class AssistantSession:
    system: str
    toolbox: Toolbox


def _editor_state_block(context: TemplateEditorContext, redactor: Redactor) -> str:
    custom = [v for v in context.variables if not v.is_auto]
    withheld = [v.name for v in context.variables if v.is_auto]
    variable_lines = [
        f"- {v.name} ({v.type}) = {redactor.redact(v.value[:MAX_VARIABLE_VALUE_CHARS])}"
        for v in custom
    ]
    return (
        "<editor_state>\n"
        f"template name: {redactor.redact(context.name) or '(unsaved)'}\n"
        f"type: {context.template_type}\n"
        f"description: {redactor.redact(context.description or '')}\n"
        "custom variables (user-defined, values shown):\n"
        f"{chr(10).join(variable_lines) or '(none)'}\n"
        "device/run variables present in the editor (values withheld): "
        f"{', '.join(withheld) or '(none)'}\n"
        "<content>\n"
        f"{redactor.redact(context.content)}\n"
        "</content>\n"
        "</editor_state>"
    )


def build_template_editor_session(
    *, user_id: int, context: TemplateEditorContext, reader: TemplateReader
) -> AssistantSession:
    redactor = Redactor()
    state = TemplateEditorState(context=context, reader=reader)
    tool_context = ToolContext(
        user_id=user_id, redactor=redactor, extras={"template_editor": state}
    )
    # The state block is built first so its secrets get tokens before any tool runs.
    system = "\n\n".join(
        [BASE_SYSTEM_PROMPT, TEMPLATE_EDITOR_PROMPT, _editor_state_block(context, redactor)]
    )
    return AssistantSession(system=system, toolbox=Toolbox(TEMPLATE_EDITOR_TOOLS, tool_context))
