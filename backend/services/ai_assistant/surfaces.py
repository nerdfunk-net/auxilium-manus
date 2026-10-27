"""Per-surface assembly: which tools a chat turn gets and what the model is told up front.

Surfaces send their *current* client-side state; the server decides what of it the model may see
(doc/ai_integration/AI_ASSISTANT.md §9b) and redacts it before building the prompt.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from models.ai_assistant import (
    MAX_CANVAS_JSON_CHARS,
    InventoryContext,
    ReportsContext,
    RunViewerContext,
    TemplateEditorContext,
    WorkflowCanvasContext,
)
from services.ai_assistant.data_sharing import DeviceLabeler, SharingPolicy
from services.ai_assistant.inventory_filter import describe_condition_tree, field_data_class
from services.ai_assistant.prompts import (
    BASE_SYSTEM_PROMPT,
    INVENTORY_PROMPT,
    REPORT_TEMPLATE_PROMPT,
    REPORTS_PROMPT,
    RUN_VIEWER_PROMPT,
    TEMPLATE_EDITOR_PROMPT,
    WORKFLOW_EDITOR_PROMPT,
)
from services.ai_assistant.redaction import MAX_REDACT_CHARS_PER_REQUEST, Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.glossary_tools import (
    GLOSSARY_TOOLS,
    STEP_ALIAS_TOOLS,
    StepAliasLookup,
)
from services.ai_assistant.tools.inventory_filter_tools import INVENTORY_FILTER_TOOLS
from services.ai_assistant.tools.inventory_tools import (
    INVENTORY_TOOLS,
    InventoryReader,
    InventoryState,
)
from services.ai_assistant.tools.report_tools import REPORT_TOOLS, ReportReader, ReportsState
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
        f"category: {context.category}\n"
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
    *,
    user_id: int,
    context: TemplateEditorContext,
    reader: TemplateReader,
    known_secrets: Iterable[str] = (),
) -> AssistantSession:
    redactor = Redactor()
    redactor.add_known_secrets(known_secrets)
    state = TemplateEditorState(context=context, reader=reader)
    tool_context = ToolContext(
        user_id=user_id, redactor=redactor, extras={"template_editor": state}
    )
    # The state block is built first so its secrets get tokens before any tool runs.
    prompts = [BASE_SYSTEM_PROMPT, TEMPLATE_EDITOR_PROMPT]
    if context.category == "report":
        prompts.append(REPORT_TEMPLATE_PROMPT)
    system = "\n\n".join([*prompts, _editor_state_block(context, redactor)])
    return AssistantSession(system=system, toolbox=Toolbox(TEMPLATE_EDITOR_TOOLS, tool_context))


def build_workflow_editor_session(
    *,
    user_id: int,
    context: WorkflowCanvasContext,
    registry: PluginCatalogue,
    references: ReferenceReader,
    validator: WorkflowValidator,
    may_propose: bool = True,
    glossary: StepAliasLookup | None = None,
) -> AssistantSession:
    # The canvas may be up to MAX_CANVAS_JSON_CHARS of JSON; its strings are redacted one by one.
    redactor = Redactor(max_chars=max(MAX_REDACT_CHARS_PER_REQUEST, MAX_CANVAS_JSON_CHARS))
    state = WorkflowEditorState(
        nodes=context.canvas_nodes,
        edges=context.canvas_edges,
        groups=context.canvas_groups,
        static_attributes=context.static_attributes,
        registry=registry,
        references=references,
        validator=validator,
    )
    extras: dict[str, Any] = {"workflow_editor": state}
    if glossary is not None:
        extras["glossary"] = glossary
    tool_context = ToolContext(user_id=user_id, redactor=redactor, extras=extras)
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
    # A user without ``workflows:write`` can still be advised, but gets no proposal tool (S5-08).
    tools = tuple(t for t in WORKFLOW_EDITOR_TOOLS if may_propose or t.name != "propose_workflow")
    if glossary is not None:
        tools = (*tools, *STEP_ALIAS_TOOLS)
    return AssistantSession(system=system, toolbox=Toolbox(tools, tool_context))


def build_run_viewer_session(
    *,
    user_id: int,
    context: RunViewerContext,
    reader: RunReader,
    sharing: SharingPolicy,
    known_secrets: Iterable[str] = (),
) -> AssistantSession:
    state = RunViewerState(run_id=context.run_id, reader=reader, labeler=DeviceLabeler(sharing))
    redactor = Redactor()
    redactor.add_known_secrets(known_secrets)
    tool_context = ToolContext(
        user_id=user_id, redactor=redactor, extras={"run_viewer": state}, sharing=sharing
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
    may_propose: bool = True,
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
            _current_filter_block(context, tool_context.redactor, sharing),
        ]
    )
    # Saving an inventory needs sources.nautobot:write; without it the user could not keep a
    # proposal, so the tool is not offered (the workflow surface does the same).
    filter_tools = tuple(
        t for t in INVENTORY_FILTER_TOOLS if may_propose or t.name != "propose_inventory"
    )
    if not may_propose:
        system += (
            "\n\nThe user may not save inventories, so you cannot propose one: you can still "
            "preview a filter to answer how many devices it would select."
        )
    toolbox = Toolbox((*INVENTORY_TOOLS, *filter_tools, *GLOSSARY_TOOLS), tool_context)
    return AssistantSession(system=system, toolbox=toolbox)


def _current_filter_block(
    context: InventoryContext, redactor: Redactor, sharing: SharingPolicy
) -> str:
    """What is in the builder now. Condition values can be device names, so they are class B."""
    tree = context.filter_tree
    items = tree.get("items") if isinstance(tree, dict) else None
    if not isinstance(items, list) or not items:
        return "The inventory builder's current filter is empty."
    if not sharing.inventory:
        return (
            f"The inventory builder's current filter has {len(items)} condition(s) or group(s); "
            "their contents are not shared with you."
        )
    # Prefix and custom-field values are addresses / possibly secrets: their own switches apply.
    described = redactor.redact(
        describe_condition_tree(
            tree, hide=lambda field: not sharing.allows(field_data_class(field))
        )
    )
    return (
        "<current_filter>\nThe inventory builder's current (maybe unsaved) filter:\n"
        f"{described}\n</current_filter>"
    )


def build_reports_session(
    *,
    user_id: int,
    context: ReportsContext,
    reader: ReportReader,
    sharing: SharingPolicy,
) -> AssistantSession:
    tool_context = ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={"reports": ReportsState(reader=reader, source_id=context.source_id)},
        sharing=sharing,
    )
    shared = "report values" if sharing.report_data else "no report values (only the catalog)"
    system = "\n\n".join(
        [BASE_SYSTEM_PROMPT, REPORTS_PROMPT, f"Data the user shares with you: {shared}."]
    )
    return AssistantSession(system=system, toolbox=Toolbox(REPORT_TOOLS, tool_context))
