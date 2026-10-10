"""Tools for the workflow-builder surface: step catalogue, references, validate, propose.

Read-only plus one proposal tool. ``propose_workflow`` never persists: it expands the model's
compact plan onto the canvas the user has open, runs the same validation as saving/running, and
only when that is clean hands the client a change set to apply into the unsaved builder.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.plugins import PluginDefinition
from services.ai_assistant.redaction import Redactor, SecretRelocationError
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.workflow_expand import (
    ExpandedWorkflow,
    PlanError,
    WorkflowPlanIn,
    expand_plan,
)

MAX_LISTED_STEPS = 200
_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "workflow_reference.md"

ReferenceKind = Literal["credentials", "git_repositories", "sources", "inventories"]


class ReferencePermissionError(Exception):
    """The calling user may not list this kind of reference."""


class Finding(Protocol):
    node_id: str | None
    tier: int
    severity: str
    code: str
    message: str


class ValidationOutcome(Protocol):
    findings: Sequence[Any]
    has_errors: bool


class PluginCatalogue(Protocol):
    def list_plugins(self, include_disabled: bool = False) -> list[PluginDefinition]: ...

    def get_plugin(
        self, plugin_id: str, include_disabled: bool = False
    ) -> PluginDefinition | None: ...

    def get_plugin_config(self, plugin_id: str) -> dict[str, Any] | None: ...


class ReferenceReader(Protocol):
    async def list_references(self, kind: str) -> list[dict[str, Any]]: ...


class WorkflowValidator(Protocol):
    async def validate(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> ValidationOutcome: ...


@dataclass(frozen=True)
class WorkflowEditorState:
    """The builder canvas as the user has it right now (raw persisted shape, unredacted)."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    static_attributes: list[dict[str, Any]]
    registry: PluginCatalogue
    references: ReferenceReader
    validator: WorkflowValidator


def _state(ctx: ToolContext) -> WorkflowEditorState:
    return ctx.extras["workflow_editor"]


@cache
def _reference_text() -> str:
    return _REFERENCE_PATH.read_text(encoding="utf-8")


# -- inputs -----------------------------------------------------------------------------------


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListStepsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100, description="Palette category")


class StepSchemaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=100)


class ListReferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReferenceKind


class ValidatePlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: WorkflowPlanIn


class ProposeWorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: WorkflowPlanIn
    summary: str = Field(min_length=1, max_length=500)


# -- formatting ---------------------------------------------------------------------------------


def _format_findings(findings: Sequence[Any]) -> str:
    return "\n".join(
        f"- {f.severity} [tier {f.tier}] {f.node_id or 'workflow'} ({f.code}): {f.message}"
        for f in findings
    )


def _step_line(plugin: PluginDefinition) -> str:
    flow = f"{','.join(plugin.requires) or '-'} -> {','.join(plugin.produces) or '-'}"
    return (
        f"{plugin.id} | {plugin.name} | {plugin.palette_category or plugin.artifact_type} | "
        f"{flow} | {plugin.overview}"
    )


def _field_line(field: Any) -> str:
    required = "required" if field.required else "optional"
    default = f", default={json.dumps(field.default)}" if field.default is not None else ""
    return f"- {field.name} ({field.data_type}, {required}{default}): {field.description}"


# -- handlers -----------------------------------------------------------------------------------


async def _get_reference(ctx: ToolContext, args: NoInput) -> ToolOutput:
    return ToolOutput(_reference_text())


async def _list_steps(ctx: ToolContext, args: ListStepsInput) -> ToolOutput:
    needle = (args.search or "").lower()
    steps = [
        p
        for p in _state(ctx).registry.list_plugins()
        if p.executable
        and (not args.category or (p.palette_category or p.artifact_type) == args.category)
        and (not needle or needle in f"{p.id} {p.name} {p.overview}".lower())
    ]
    if not steps:
        return ToolOutput("No steps match.")
    lines = [_step_line(p) for p in steps[:MAX_LISTED_STEPS]]
    return ToolOutput("id | name | category | requires -> produces | overview\n" + "\n".join(lines))


async def _get_step_schema(ctx: ToolContext, args: StepSchemaInput) -> ToolOutput:
    registry = _state(ctx).registry
    plugin = registry.get_plugin(args.step_id)
    if plugin is None or not plugin.executable:
        return ToolOutput(f"Unknown step '{args.step_id}'. Use list_steps.", is_error=True)
    defaults = await asyncio.to_thread(registry.get_plugin_config, plugin.id) or {}
    fields = [_field_line(f) for f in plugin.metadata.configuration_input] or ["(no configuration)"]
    parts = [
        f"id: {plugin.id}",
        f"name: {plugin.name}",
        f"description: {plugin.description}",
        f"requires: {plugin.requires} produces: {plugin.produces} consumes: {plugin.consumes}",
        f"requires_parsed: {plugin.requires_parsed} produces_parsed: {plugin.produces_parsed}",
        f"outcomes: {', '.join(o.name for o in plugin.outcomes) or 'none'}",
        "configuration (pluginConfig keys):",
        *fields,
    ]
    if defaults:
        parts.append(
            "defaults the step applies when a field is left blank: "
            + json.dumps(defaults, default=str)
        )
    return ToolOutput("\n".join(parts))


async def _list_references(ctx: ToolContext, args: ListReferencesInput) -> ToolOutput:
    try:
        rows = await _state(ctx).references.list_references(args.kind)
    except ReferencePermissionError:
        return ToolOutput(f"You do not have permission to list {args.kind}.", is_error=True)
    if not rows:
        return ToolOutput(f"No {args.kind} are available to you.")
    return ToolOutput("\n".join(json.dumps(row, default=str) for row in rows))


def _restored_plan(ctx: ToolContext, plan: WorkflowPlanIn) -> WorkflowPlanIn:
    """Put real values back where the model echoed redaction tokens."""
    redactor = ctx.redactor
    nodes = [n.model_copy(update={"config": redactor.restore_data(n.config)}) for n in plan.nodes]
    static = (
        redactor.restore_data(plan.static_attributes)
        if plan.static_attributes is not None
        else None
    )
    return plan.model_copy(update={"nodes": nodes, "static_attributes": static})


async def _expand_and_validate(
    ctx: ToolContext, plan: WorkflowPlanIn
) -> tuple[ExpandedWorkflow | None, list[Any], ToolOutput | None]:
    state = _state(ctx)
    try:
        restored = _restored_plan(ctx, plan)
    except SecretRelocationError as exc:
        return (
            None,
            [],
            ToolOutput(
                f"The plan is invalid: {exc}. Keep each __SECRET_n__ token in the field it came "
                "from, or remove it.",
                is_error=True,
            ),
        )
    if Redactor.data_contains_placeholder(restored.model_dump(mode="json")):
        return (
            None,
            [],
            ToolOutput(
                "The plan contains a ***REDACTED*** marker, which would be saved as a literal "
                "value. Keep the __SECRET_n__ token or remove the field.",
                is_error=True,
            ),
        )
    try:
        expanded = expand_plan(
            restored,
            current_nodes=state.nodes,
            current_edges=state.edges,
            current_groups=state.groups,
            current_static_attributes=state.static_attributes,
            registry=state.registry,
        )
    except PlanError as exc:
        return (
            None,
            [],
            ToolOutput(
                "The plan is invalid:\n" + "\n".join(f"- {m}" for m in exc.messages), is_error=True
            ),
        )
    outcome = await state.validator.validate(expanded.nodes, expanded.edges)
    return expanded, list(outcome.findings), None


async def _validate_plan(ctx: ToolContext, args: ValidatePlanInput) -> ToolOutput:
    expanded, findings, failure = await _expand_and_validate(ctx, args.plan)
    if failure is not None:
        return failure
    if not findings:
        return ToolOutput("Validation passed with no findings.")
    errors = [f for f in findings if f.severity == "error"]
    return ToolOutput(
        f"{len(errors)} error(s), {len(findings) - len(errors)} warning(s):\n"
        + _format_findings(findings),
        is_error=bool(errors),
    )


def _is_noop(expanded: ExpandedWorkflow) -> bool:
    changes = expanded.changes
    return not (
        changes["nodes_added"]
        or changes["nodes_removed"]
        or changes["nodes_changed"]
        or changes["edges_added"]
        or changes["edges_removed"]
        or changes["static_attributes_changed"]
    )


async def _propose_workflow(ctx: ToolContext, args: ProposeWorkflowInput) -> ToolOutput:
    expanded, findings, failure = await _expand_and_validate(ctx, args.plan)
    if failure is not None or expanded is None:
        return failure or ToolOutput("The plan could not be expanded.", is_error=True)
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        return ToolOutput(
            f"Validation found {len(errors)} error(s); nothing was proposed. Fix them and propose "
            "again:\n" + _format_findings(findings),
            is_error=True,
        )
    if _is_noop(expanded):
        return ToolOutput("The plan is identical to the current workflow.", is_error=True)

    warnings = [f for f in findings if f.severity != "error"]
    proposal = {
        "kind": "workflow",
        "summary": args.summary,
        "canvas_nodes": expanded.nodes,
        "canvas_edges": expanded.edges,
        "canvas_groups": expanded.groups,
        "static_attributes": expanded.static_attributes,
        "changes": expanded.changes,
        "warnings": [
            {"node_id": f.node_id, "code": f.code, "message": f.message} for f in warnings
        ],
    }
    message = (
        "Proposal accepted and shown to the user as a change list with Apply/Reject. It is NOT "
        "applied yet; do not say it was. Briefly explain what you changed and why."
    )
    if warnings:
        message += " Warnings shown to the user:\n" + _format_findings(warnings)
    return ToolOutput(message, proposal=proposal)


WORKFLOW_EDITOR_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_workflow_reference",
        "Rules for authoring workflows here: the plan format, outcomes, capability flow, fan-out / "
        "fan-in, static attributes, references and secrets. Read it before your first proposal.",
        NoInput,
        _get_reference,
    ),
    Tool(
        "list_steps",
        "List workflow steps (id | name | category | requires -> produces | overview), optionally "
        "filtered by a search string or palette category. Use it to pick step kinds.",
        ListStepsInput,
        _list_steps,
    ),
    Tool(
        "get_step_schema",
        "Full detail of one step: configuration fields (name, type, required, default), outcomes "
        "and capabilities. Call it for every step you configure; never guess config fields.",
        StepSchemaInput,
        _get_step_schema,
    ),
    Tool(
        "list_references",
        "List real credentials (id, name, type - never secrets), git repositories, sources or "
        "saved inventories available to the user, so references in step config are real.",
        ListReferencesInput,
        _list_references,
    ),
    Tool(
        "validate_workflow",
        "Check a complete plan (schema, references, capability flow, attribute paths) without "
        "proposing it. Same checks as saving and running.",
        ValidatePlanInput,
        _validate_plan,
    ),
    Tool(
        "propose_workflow",
        "Propose the COMPLETE new workflow plan (all steps and edges, not a diff). The server "
        "expands and validates it; only a plan without errors is shown to the user as a change "
        "list to apply or reject. It never changes anything by itself.",
        ProposeWorkflowInput,
        _propose_workflow,
    ),
)
