"""Tools for the template-editor surface: references, example templates, render, propose.

Pure reads plus one proposal tool. ``propose_template`` never persists anything; it hands the
client a diff to apply into the unsaved editor buffer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.ai_assistant import EditorVariableIn, TemplateEditorContext
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.template_render import build_context, check_syntax, render_lenient
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

MAX_CONTENT_CHARS = 200000
RENDER_TIMEOUT_SECONDS = 5.0
MAX_RENDER_OUTPUT_CHARS = 8000
_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "template_reference.md"


class TemplatePermissionError(Exception):
    """The calling user may not read templates."""


class TemplateReader(Protocol):
    async def list_templates(self, search: str | None, limit: int) -> list[dict[str, Any]]: ...

    async def get_template(self, template_id: int) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class TemplateEditorState:
    """The editor as the user has it right now (unredacted; never sent to the model as is)."""

    context: TemplateEditorContext
    reader: TemplateReader

    @property
    def variables(self) -> Sequence[EditorVariableIn]:
        return self.context.variables


def _state(ctx: ToolContext) -> TemplateEditorState:
    return ctx.extras["template_editor"]


@cache
def _reference_text() -> str:
    return _REFERENCE_PATH.read_text(encoding="utf-8")


# -- inputs -----------------------------------------------------------------


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListTemplatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=20, ge=1, le=50)


class GetTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: int = Field(ge=1)


class RenderTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=MAX_CONTENT_CHARS)
    sample_variables: dict[str, Any] = Field(default_factory=dict)


class ProposeTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_CONTENT_CHARS)
    summary: str = Field(min_length=1, max_length=500)


# -- handlers ---------------------------------------------------------------


async def _get_reference(ctx: ToolContext, args: NoInput) -> ToolOutput:
    return ToolOutput(_reference_text())


async def _list_templates(ctx: ToolContext, args: ListTemplatesInput) -> ToolOutput:
    try:
        rows = await _state(ctx).reader.list_templates(args.search, args.limit)
    except TemplatePermissionError:
        return ToolOutput("You do not have permission to read templates.", is_error=True)
    if not rows:
        return ToolOutput("No templates found.")
    lines = [
        f"{row['id']} | {row['name']} | {row['template_type']} | {row['category']} | "
        f"{(row.get('description') or '').strip()[:120]}"
        for row in rows
    ]
    return ToolOutput("id | name | type | category | description\n" + "\n".join(lines))


async def _get_template(ctx: ToolContext, args: GetTemplateInput) -> ToolOutput:
    try:
        row = await _state(ctx).reader.get_template(args.template_id)
    except TemplatePermissionError:
        return ToolOutput("You do not have permission to read templates.", is_error=True)
    if row is None:
        return ToolOutput(f"Template {args.template_id} not found.", is_error=True)
    variables = row.get("variables") or {}
    variable_lines = [f"{name} ({spec.get('type', 'custom')})" for name, spec in variables.items()]
    return ToolOutput(
        f"name: {row['name']}\ntype: {row['template_type']}\ncategory: {row['category']}\n"
        f"description: {row.get('description') or ''}\n"
        f"commands run to populate variables: {row.get('pre_run_commands') or []}\n"
        f"nautobot attribute groups: {row.get('nautobot_attributes') or []}\n"
        f"variables: {', '.join(variable_lines) or 'none'}\n"
        f"--- content ---\n{row.get('content', '')}"
    )


async def _render_with_timeout(content: str, context: dict[str, Any]) -> Any:
    return await asyncio.wait_for(
        asyncio.to_thread(render_lenient, content, context), timeout=RENDER_TIMEOUT_SECONDS
    )


def _format_withheld(names: Sequence[str]) -> str:
    return (
        "Variables not available to you (device/run data is withheld) rendered as <<name>>: "
        + ", ".join(names)
        if names
        else ""
    )


async def _render_template(ctx: ToolContext, args: RenderTemplateInput) -> ToolOutput:
    state = _state(ctx)
    # Never restore tokens here: the rendered output goes back to the model, so restoring would
    # let it read any redacted secret (e.g. ``{{ '__SECRET_1__' | list }}``). Only proposals,
    # which go to the user, restore.
    content = (
        args.content if args.content is not None else ctx.redactor.redact(state.context.content)
    )
    context = build_context(state.variables, args.sample_variables)
    try:
        outcome = await _render_with_timeout(content, context)
    except TimeoutError:
        return ToolOutput("Rendering timed out; the template may loop too long.", is_error=True)
    if not outcome.ok:
        where = f" (line {outcome.error_line})" if outcome.error_line else ""
        extra = _format_withheld(outcome.withheld)
        return ToolOutput(
            f"Render error{where}: {outcome.error}" + (f"\n{extra}" if extra else ""),
            is_error=True,
        )
    output = outcome.output
    if len(output) > MAX_RENDER_OUTPUT_CHARS:
        output = output[:MAX_RENDER_OUTPUT_CHARS] + "\n…[rendered output truncated]"
    notes = _format_withheld(outcome.withheld)
    return ToolOutput(f"Rendered output:\n{output}" + (f"\n\n{notes}" if notes else ""))


async def _propose_template(ctx: ToolContext, args: ProposeTemplateInput) -> ToolOutput:
    state = _state(ctx)
    content = ctx.redactor.restore(args.content)
    if Redactor.contains_unresolved_placeholder(content):
        return ToolOutput(
            "The content contains a ***REDACTED*** marker, which would be saved as a literal "
            "value. Use a Jinja variable or remove that line.",
            is_error=True,
        )
    if content == state.context.content:
        return ToolOutput(
            "The proposed content is identical to the current template.", is_error=True
        )
    problem = check_syntax(content)
    if problem is not None:
        where = f" at line {problem.line}" if problem.line else ""
        return ToolOutput(
            f"Jinja syntax error{where}: {problem.message}. Fix it and propose again.",
            is_error=True,
        )

    warnings: list[str] = []
    try:
        outcome = await _render_with_timeout(content, build_context(state.variables))
        if not outcome.ok:
            warnings.append(f"Trial render raised: {outcome.error}")
    except TimeoutError:
        warnings.append("Trial render timed out; check loops for runaway iteration.")

    proposal = {
        "kind": "template",
        "content": content,
        "summary": args.summary,
        "warnings": warnings,
    }
    message = (
        "Proposal accepted and shown to the user as a diff with Apply/Reject. It is NOT applied "
        "yet; do not say it was. Briefly explain the change."
    )
    if warnings:
        message += " Warnings (fix and re-propose if they are real problems): " + "; ".join(
            warnings
        )
    return ToolOutput(message, proposal=proposal)


TEMPLATE_EDITOR_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_template_reference",
        "Reference for writing templates in this app: which variables exist (device, nautobot, "
        "commands, parsed.*, run_input, ...), their paths, and examples. Call it before using a "
        "variable path you are not sure about.",
        NoInput,
        _get_reference,
    ),
    Tool(
        "list_templates",
        "List saved templates (id, name, type, category, description), optionally filtered by a "
        "search string. Use to find examples to learn from.",
        ListTemplatesInput,
        _list_templates,
    ),
    Tool(
        "get_template",
        "Read one saved template (content, variables, commands) by id, as an example.",
        GetTemplateInput,
        _get_template,
    ),
    Tool(
        "render_template",
        "Trial-render a template (default: the current editor content) with the user's custom "
        "variables plus optional sample_variables you invent. Device and run variables are "
        "withheld and render as <<name>>. Use to check syntax and logic.",
        RenderTemplateInput,
        _render_template,
    ),
    Tool(
        "propose_template",
        "Propose a new full content for the template. Validates Jinja syntax and shows the user a "
        "diff to apply or reject. Always send the COMPLETE new template, not a fragment. It never "
        "changes anything by itself.",
        ProposeTemplateInput,
        _propose_template,
    ),
)
