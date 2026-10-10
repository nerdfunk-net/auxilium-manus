"""Per-surface assembly: which tools a chat turn gets and what the model is told up front.

Surfaces send their *current* client-side state; the server decides what of it the model may see
(doc/ai_integration/AI_ASSISTANT.md §9b) and redacts it before building the prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from models.ai_assistant import (
    InventoryContext,
    RunViewerContext,
    TemplateEditorContext,
    WorkflowCanvasContext,
)
from services.ai_assistant.data_sharing import DeviceLabeler, SharingPolicy
from services.ai_assistant.prompts import (
    BASE_SYSTEM_PROMPT,
    INVENTORY_PROMPT,
    RUN_VIEWER_PROMPT,
    TEMPLATE_EDITOR_PROMPT,
    WORKFLOW_EDITOR_PROMPT,
)
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.inventory_tools import (
    INVENTORY_TOOLS,
    InventoryReader,
    InventoryState,
)
from services.ai_assistant.tools.run_tools import RUN_VIEWER_TOOLS, RunReader, RunViewerState
from services.ai_assistant.tools.template_tools import (
    TEMPLATE_EDITOR_TOOLS,
    TemplateEditorState,
    TemplateReader,
)
from services.ai_assistant.tools.workflow_tools import (
    WORKFLOW_EDITOR_TOOLS,
    PluginCatalogue,
    ReferenceReader,
    WorkflowEditorState,
    WorkflowValidator,
)
from services.ai_assistant.workflow_expand import build_compact_view

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


def build_workflow_editor_session(
    *,
    user_id: int,
    context: WorkflowCanvasContext,
    registry: PluginCatalogue,
    references: ReferenceReader,
    validator: WorkflowValidator,
) -> AssistantSession:
    redactor = Redactor()
    state = WorkflowEditorState(
        nodes=context.canvas_nodes,
        edges=context.canvas_edges,
        groups=context.canvas_groups,
        static_attributes=context.static_attributes,
        registry=registry,
        references=references,
        validator=validator,
    )
    tool_context = ToolContext(
        user_id=user_id, redactor=redactor, extras={"workflow_editor": state}
    )
    # Built first so secrets in step configs get their tokens before any tool runs.
    view = build_compact_view(
        context.canvas_nodes, context.canvas_edges, context.static_attributes, redactor
    )
    canvas_block = (
        "<canvas_state>\n"
        f"workflow name: {redactor.redact(context.name) or '(unsaved)'}\n"
        f"{json.dumps(view, default=str)}\n"
        "</canvas_state>"
    )
    system = "\n\n".join([BASE_SYSTEM_PROMPT, WORKFLOW_EDITOR_PROMPT, canvas_block])
    return AssistantSession(system=system, toolbox=Toolbox(WORKFLOW_EDITOR_TOOLS, tool_context))


def build_run_viewer_session(
    *,
    user_id: int,
    context: RunViewerContext,
    reader: RunReader,
    sharing: SharingPolicy,
) -> AssistantSession:
    state = RunViewerState(run_id=context.run_id, reader=reader, labeler=DeviceLabeler(sharing))
    tool_context = ToolContext(
        user_id=user_id, redactor=Redactor(), extras={"run_viewer": state}, sharing=sharing
    )
    opened = (
        f"The user has run {context.run_id} open."
        if context.run_id is not None
        else "No run is open; ask which run (id) to look at."
    )
    sharing_line = f"Data the user shares with you: {sharing.describe()}."
    system = "\n\n".join([BASE_SYSTEM_PROMPT, RUN_VIEWER_PROMPT, opened, sharing_line])
    return AssistantSession(system=system, toolbox=Toolbox(RUN_VIEWER_TOOLS, tool_context))


def build_inventory_session(
    *,
    user_id: int,
    context: InventoryContext,
    reader: InventoryReader,
    sharing: SharingPolicy,
) -> AssistantSession:
    tool_context = ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={"inventory": InventoryState(reader=reader)},
        sharing=sharing,
    )
    shared = sharing.describe() if sharing.inventory else "nothing about individual devices"
    system = "\n\n".join(
        [
            BASE_SYSTEM_PROMPT,
            INVENTORY_PROMPT,
            f"Data the user shares with you: {shared}.",
        ]
    )
    return AssistantSession(system=system, toolbox=Toolbox(INVENTORY_TOOLS, tool_context))
