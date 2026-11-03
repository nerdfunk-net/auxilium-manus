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

from services.ai_assistant.device_access import DEVICE_DRIVERS, DeviceAccessError
from services.ai_assistant.released_run_builder import MAX_DEVICES
from services.ai_assistant.released_workflow_reader import (
    ReleasedWorkflow,
    ReleasedWorkflowAccessError,
    ReleasedWorkflowReader,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.device_tools import DeviceName
from services.ai_assistant.tools.run_tools import RUN_VIEWER_KEY, RunAccessError, read_step_result
from services.ai_assistant.workflow_run_token import issue_run_token
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs

# ``ToolContext.extras`` slot holding the ``ReleasedWorkflowReader``.
RELEASED_WORKFLOWS_KEY = "released_workflows"
MAX_DEVICES_PER_START = MAX_DEVICES
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
    devices: list[DeviceName] = Field(
        default_factory=list,
        max_length=MAX_DEVICES_PER_START,
        description=(
            "Devices the workflow acts on: names exactly as in the inventory, or (only when "
            "describe_workflow says addresses outside the inventory are accepted) a single IPv4 "
            "address such as 10.1.2.3"
        ),
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
    listing: dict[str, Any] = {"workflows": rows, "total": len(workflows)}
    if len(workflows) > MAX_LISTED:
        listing["note"] = (
            f"Only the first {MAX_LISTED} of {len(workflows)} released workflows are listed. "
            "A workflow that is not here may still exist: ask the user for its name or id and "
            "use describe_workflow."
        )
    return ToolOutput(_json(listing))


def _reserved(workflow: ReleasedWorkflow, attr: dict[str, Any]) -> bool:
    """An input only the system or the confirming user fills: the model never sets it."""
    return _user_only(attr) or attr.get("name") == workflow.devices_input


def _model_settable(workflow: ReleasedWorkflow) -> list[dict[str, Any]]:
    """The inputs the model may set: not the devices input, not a credential, not a secret."""
    return [
        _input_view(dict(a)) for a in workflow.static_attributes if not _reserved(workflow, dict(a))
    ]


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
        "inputs": _model_settable(workflow),
        "devices": {
            "takes_devices": workflow.devices_input is not None,
            "max": MAX_DEVICES_PER_START,
            "accepts_ipv4_outside_inventory": workflow.allow_free_ip,
        },
        "chosen_by_the_user_on_the_card": list(workflow.credential_inputs),
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
        if name in by_name and _reserved(workflow, by_name[name]):
            return f"Input '{name}' is not set by the assistant; do not supply it."
    for attr in attrs:
        if not _user_only(attr) or not attr.get("required") or attr.get("default") is not None:
            continue
        if attr.get("name") in workflow.credential_inputs:
            continue  # the user picks it on the card
        return (
            f"Input '{attr.get('name')}' is required and only the user may provide it, so the "
            "assistant cannot start this workflow. Tell the user to start it from the workflow "
            "page (or ask its releaser to mark it as chosen on the card)."
        )
    return None


def _shown_inputs(
    workflow: ReleasedWorkflow, resolved: dict[str, Any], filled_elsewhere: set[str]
) -> dict[str, Any]:
    """The inputs the run starts with, defaults included, as the card shows them.

    Left out: the devices input and the credential inputs (the server and the user fill those) and
    secrets (never shown, never in a token).
    """
    secrets = {a.get("name") for a in workflow.static_attributes if a.get("type") == "secret"}
    return {k: v for k, v in resolved.items() if k not in filled_elsewhere and k not in secrets}


def _devices_problem(workflow: ReleasedWorkflow, refs: list[str]) -> str | None:
    if workflow.devices_input is None and refs:
        return "This workflow does not take devices; leave 'devices' empty."
    if workflow.devices_input is not None and not refs:
        return "This workflow needs at least one device in 'devices'."
    return None


async def _propose(ctx: ToolContext, args: ProposeRunInput) -> ToolOutput:
    reader = _reader(ctx)
    try:
        workflow = await reader.get_released(args.workflow_id)
    except ReleasedWorkflowAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    refusal = _refusal(workflow, args.inputs) or _devices_problem(workflow, args.devices)
    if refusal:
        return ToolOutput(refusal, is_error=True)
    # The devices and the credentials arrive later (resolved here / chosen on the card); stand in
    # for them so the check only judges what the model supplied.
    stand_ins: dict[str, Any] = {name: "x" for name in workflow.credential_inputs}
    if workflow.devices_input:
        stand_ins[workflow.devices_input] = "x"
    try:
        # Validates names, required values and types now so the model can fix its call, and
        # fills the defaults: the card and the token carry what will actually run.
        resolved = resolve_run_inputs(
            list(workflow.static_attributes),
            {**args.inputs, **stand_ins},
            sealer=lambda _v: {},
        )
    except RunInputValidationError as exc:
        return ToolOutput(f"Invalid inputs: {exc}", is_error=True)
    shown = _shown_inputs(workflow, resolved, set(stand_ins))
    try:
        devices = await reader.resolve_devices(args.devices, allow_free_ip=workflow.allow_free_ip)
    except DeviceAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    token, expires_at = issue_run_token(
        user_id=ctx.user_id,
        workflow_id=workflow.id,
        run_inputs=shown,
        devices=devices,
        stamp=workflow.release_stamp,
    )
    ctx.audit_refs.add(f"workflow:{workflow.id}")
    proposal = {
        "kind": "workflow_run",
        "token": token,
        "expires_at": expires_at,
        "workflow": {"id": workflow.id, "name": workflow.name},
        "inputs": shown,
        "devices": [{"name": d.label, "ip": d.ip, "in_inventory": d.in_inventory} for d in devices],
        # What the user fills in on the card: never the model.
        "credential_inputs": list(workflow.credential_inputs),
        # For addresses outside the inventory the card asks the user for the device type, from this
        # closed list; the model has no say in it.
        "driver_choices": list(DEVICE_DRIVERS) if any(not d.in_inventory for d in devices) else [],
    }
    message = (
        f"A card to run '{workflow.name}' was shown to the user with Run/Reject. It is NOT "
        "started yet; do not say it was. The user chooses their own credential on the card. "
        "When they confirm, they will tell you the run id: read it with get_run and, when "
        "finished, get_run_result. Briefly say what you asked to run."
    )
    return ToolOutput(message, proposal=proposal)


async def _run_result(ctx: ToolContext, args: RunResultInput) -> ToolOutput:
    state = ctx.extras[RUN_VIEWER_KEY]
    try:
        run = await state.reader.get_run(args.run_id)
    except RunAccessError:
        return ToolOutput(
            "No released-workflow result is available for that run (not found or no access). "
            "get_run still shows its status if you may see it.",
            is_error=True,
        )
    # The step is the one designated when this run was started; a later release cannot move it.
    node_id = run.get("ai_result_node_id")
    if run.get("trigger_type") != "ai_assistant" or not node_id:
        return ToolOutput(
            "This run was not started from a released workflow with a designated result step; "
            "use get_run for the step statuses.",
            is_error=True,
        )
    if run.get("status") not in ("success", "failed", "cancelled"):
        return ToolOutput(f"The run is {run.get('status')}; ask again when it has finished.")
    ctx.audit_refs.add(f"run:{args.run_id}")
    return await read_step_result(ctx, args.run_id, node_id, ["parsed"])


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
