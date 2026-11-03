"""Released workflows for Ask the Net (doc/AI_TOOL_CHAIN.md §16).

A person with ``workflows:release_ai`` releases a reviewed workflow; the model selects and
parameterises it, the user confirms, the normal run engine executes it. Tools here are reads or one
proposal: ``propose_workflow_run`` starts nothing, the user's click on the card does
(``POST /ai/exec/workflow-run``). The result is read from the run's stored step output (the one
step the releaser designated), through the same gates as ``get_step_result``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.device_access import DeviceAccessError
from services.ai_assistant.released_workflow_reader import (
    ReleasedWorkflow,
    ReleasedWorkflowAccessError,
    ReleasedWorkflowReader,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.run_tools import RUN_VIEWER_KEY, RunAccessError, read_step_result
from services.ai_assistant.workflow_run_token import issue_run_token
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs

# ``ToolContext.extras`` slot holding the ``ReleasedWorkflowReader``.
RELEASED_WORKFLOWS_KEY = "released_workflows"
MAX_DEVICES_PER_START = 20
MAX_LISTED = 50
_SHORT_DESCRIPTION_CHARS = 200
# Inputs the model must never fill in: the user supplies them (secrets), or they pick a stored
# credential the model should not choose.
_USER_ONLY_KINDS = frozenset({"secret"})

InputValue = str | int | float | bool


def _reader(ctx: ToolContext) -> ReleasedWorkflowReader:
    return ctx.extras[RELEASED_WORKFLOWS_KEY]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _user_only(attr: dict[str, Any]) -> bool:
    return attr.get("type") in _USER_ONLY_KINDS or (
        attr.get("type") == "reference" and attr.get("ref_kind") == "credential"
    )


def _input_view(attr: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": attr.get("name"),
        "type": attr.get("type"),
        "required": bool(attr.get("required")),
        "default": None if _user_only(attr) else attr.get("default"),
        "set_by": "the user, not the assistant" if _user_only(attr) else "the assistant",
    }


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: int = Field(ge=1, description="id from list_released_workflows")


class ProposeRunInput(WorkflowRef):
    inputs: dict[str, InputValue] = Field(
        default_factory=dict, description="Values for the inputs listed by describe_workflow"
    )
    devices: list[str] = Field(
        default_factory=list,
        max_length=MAX_DEVICES_PER_START,
        description="Device names exactly as in the inventory, when the workflow needs devices",
    )


class RunResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1, description="Run id the user started from the card")


async def _list_released(ctx: ToolContext, _args: NoInput) -> ToolOutput:
    try:
        workflows = await _reader(ctx).list_released()
    except ReleasedWorkflowAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    if not workflows:
        return ToolOutput("No workflow is released for you.")
    rows = [
        {"id": w.id, "name": w.name, "summary": w.description[:_SHORT_DESCRIPTION_CHARS]}
        for w in workflows[:MAX_LISTED]
    ]
    return ToolOutput(_json({"workflows": rows}))


async def _describe(ctx: ToolContext, args: WorkflowRef) -> ToolOutput:
    try:
        workflow = await _reader(ctx).get_released(args.workflow_id)
    except ReleasedWorkflowAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    ctx.audit_refs.add(f"workflow:{workflow.id}")
    view = {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "inputs": [_input_view(dict(a)) for a in workflow.static_attributes],
        "max_devices": MAX_DEVICES_PER_START,
        "has_designated_result": workflow.result_node_id is not None,
        "note": (
            "Starting needs the user's confirmation. Use propose_workflow_run, then read the "
            "outcome with get_run and get_run_result once the user says it has finished."
        ),
    }
    return ToolOutput(_json(view))


def _refusal(workflow: ReleasedWorkflow, supplied: dict[str, InputValue]) -> str | None:
    """Why the model may not start this workflow, or ``None``."""
    attrs = [dict(a) for a in workflow.static_attributes]
    by_name = {a.get("name"): a for a in attrs}
    for name in supplied:
        if name in by_name and _user_only(by_name[name]):
            return f"Input '{name}' is set by the user, not the assistant; do not supply it."
    for attr in attrs:
        if _user_only(attr) and attr.get("required") and attr.get("default") is None:
            return (
                f"Input '{attr.get('name')}' is required and only the user may provide it, so "
                "the assistant cannot start this workflow. Tell the user to start it from the "
                "workflow page."
            )
    return None


async def _propose(ctx: ToolContext, args: ProposeRunInput) -> ToolOutput:
    reader = _reader(ctx)
    try:
        workflow = await reader.get_released(args.workflow_id)
    except ReleasedWorkflowAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    refusal = _refusal(workflow, args.inputs)
    if refusal:
        return ToolOutput(refusal, is_error=True)
    try:
        # Validates names, required values and types now so the model can fix its call. The
        # supplied (not the resolved) values go into the token: the start resolves them again.
        resolve_run_inputs(
            list(workflow.static_attributes), dict(args.inputs), sealer=lambda _v: {}
        )
    except RunInputValidationError as exc:
        return ToolOutput(f"Invalid inputs: {exc}", is_error=True)
    try:
        devices = await reader.resolve_devices(args.devices)
    except DeviceAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    token, expires_at = issue_run_token(
        user_id=ctx.user_id,
        workflow_id=workflow.id,
        run_inputs=dict(args.inputs),
        device_ids=[device_id for device_id, _name in devices],
    )
    ctx.audit_refs.add(f"workflow:{workflow.id}")
    proposal = {
        "kind": "workflow_run",
        "token": token,
        "expires_at": expires_at,
        "workflow": {"id": workflow.id, "name": workflow.name},
        "inputs": dict(args.inputs),
        "devices": [{"id": device_id, "name": name} for device_id, name in devices],
    }
    message = (
        f"A card to run '{workflow.name}' was shown to the user with Run/Reject. It is NOT "
        "started yet; do not say it was. When they confirm, they will tell you the run id: read "
        "it with get_run and, when finished, get_run_result. Briefly say what you asked to run."
    )
    return ToolOutput(message, proposal=proposal)


async def _run_result(ctx: ToolContext, args: RunResultInput) -> ToolOutput:
    state = ctx.extras[RUN_VIEWER_KEY]
    try:
        run = await state.reader.get_run(args.run_id)
        workflow = await _reader(ctx).get_released(run["workflow_id"])
    except RunAccessError, ReleasedWorkflowAccessError:
        return ToolOutput(
            "No released-workflow result is available for that run (not found, no access, or "
            "the workflow is no longer released). get_run still shows its status.",
            is_error=True,
        )
    if run.get("status") not in ("success", "failed", "cancelled"):
        return ToolOutput(f"The run is {run.get('status')}; ask again when it has finished.")
    if workflow.result_node_id is None:
        return ToolOutput(
            "This workflow designates no result step; use get_run for the step statuses."
        )
    ctx.audit_refs.add(f"run:{args.run_id}")
    return await read_step_result(ctx, args.run_id, workflow.result_node_id, ["parsed"])


def build_released_workflow_tools() -> tuple[Tool, ...]:
    return (
        Tool(
            "list_released_workflows",
            "Workflows an administrator-approved person released for you to start, with a short "
            "summary. Use before proposing a run.",
            NoInput,
            _list_released,
        ),
        Tool(
            "describe_workflow",
            "What a released workflow does, its inputs (which ones you set and which only the "
            "user can) and device limit. Read this before propose_workflow_run.",
            WorkflowRef,
            _describe,
        ),
        Tool(
            "propose_workflow_run",
            "Ask the user to start a released workflow with the inputs and devices you give. "
            "This only proposes: nothing runs until the user confirms in the card.",
            ProposeRunInput,
            _propose,
        ),
        Tool(
            "get_run_result",
            "The result the releaser designated for a finished run of a released workflow: the "
            "output of one step. Needs the content opt-in.",
            RunResultInput,
            _run_result,
        ),
    )
