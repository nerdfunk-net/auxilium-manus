"""Tools for the run-viewer surface: explain why a run failed, what a step produced.

Pure reads. This is the first surface whose tools can return class B/C data (device names and
attributes, command output, error text, run logs), so every such value goes through the user's
opt-in (``ctx.sharing``) and is replaced by a ``not_shared`` marker when the class is off.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.data_sharing import (
    DataClass,
    DeviceLabeler,
    gated,
    mask_run_attributes,
    not_shared_marker,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.workflow_expand import build_compact_view

MAX_DEVICES_LISTED = 20
MAX_EVENTS_LISTED = 100
MAX_ARTIFACT_CHARS = 8000
MAX_FIELD_CHARS = 2000
TRUNCATION_NOTE = "…[truncated; the output is longer than shown]"


class RunAccessError(Exception):
    """Run missing, or the calling user may not read it (deliberately indistinguishable)."""


class RunReader(Protocol):
    async def get_run(self, run_id: int) -> dict[str, Any]: ...

    async def list_events(
        self, run_id: int, limit: int, node_id: str | None
    ) -> list[dict[str, Any]]: ...

    async def get_artifact(self, run_id: int, artifact_id: str) -> dict[str, Any] | None: ...

    async def get_workflow(self, run_id: int) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class RunViewerState:
    run_id: int | None
    reader: RunReader
    labeler: DeviceLabeler
    # Runs already loaded this request (labels are seeded from them; see _load_run).
    loaded: dict[int, dict[str, Any]] = field(default_factory=dict)


def _state(ctx: ToolContext) -> RunViewerState:
    return ctx.extras["run_viewer"]


# -- inputs -----------------------------------------------------------------------------------


class RunRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int | None = Field(
        default=None, description="Run id; omit to use the run open in the UI"
    )


class StepResultInput(RunRef):
    node_id: str = Field(min_length=1, max_length=255, description="step_node_id from get_run")
    device: str | None = Field(default=None, max_length=255, description="Only this device")
    include: list[str] = Field(
        default_factory=list,
        max_length=2,
        description="Extra detail: 'attributes' (inventory data) and/or 'parsed' (parsed output)",
    )


class ArtifactInput(RunRef):
    artifact_id: str = Field(min_length=1, max_length=255, description="From get_step_result")


class EventsInput(RunRef):
    node_id: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=50, ge=1, le=MAX_EVENTS_LISTED)


# -- helpers ----------------------------------------------------------------------------------


def _resolve_run_id(ctx: ToolContext, run_id: int | None) -> int | None:
    return run_id if run_id is not None else _state(ctx).run_id


_NO_RUN = ToolOutput("No run is open. Ask the user which run (id) to look at.", is_error=True)
_NO_ACCESS = ToolOutput("That run does not exist or you cannot access it.", is_error=True)


def _cap_strings(value: Any) -> Any:
    """Bound every string leaf so one huge error or parsed value cannot flood the context."""
    if isinstance(value, str):
        if len(value) > MAX_FIELD_CHARS:
            return value[:MAX_FIELD_CHARS] + f" {TRUNCATION_NOTE}"
        return value
    if isinstance(value, dict):
        return {k: _cap_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap_strings(v) for v in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_cap_strings(value), default=str, indent=1)


def _device_names(run: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for group in run.get("device_groups", []):
        names.update(group.get("device_names", []))
    for step in run.get("step_results", []):
        for envelope in ((step.get("output") or {}).get("outcomes") or {}).values():
            for device in (envelope.get("devices") or {}).values():
                names.add(device.get("name") or device.get("id") or "unknown")
    return names


async def _load_run(ctx: ToolContext, run_id: int) -> dict[str, Any]:
    """Load a run once per request and seed the device labels from all of its devices in sorted
    order, so ``device-N`` does not depend on which tool the model happened to call first."""
    state = _state(ctx)
    if run_id not in state.loaded:
        run = await state.reader.get_run(run_id)
        state.labeler.seed(_device_names(run))
        state.loaded[run_id] = run
    return state.loaded[run_id]


def _device_failures(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured failure records of one device (``models.failure``).

    Closed vocabulary and numbers only, so they are metadata and are not gated; the free-text
    ``message`` next to them is class C and stays behind the opt-in.
    """
    return [
        {"step_node_id": e.get("node_id"), **e["failure"]}
        for e in (device.get("errors") or [])
        if isinstance(e, dict) and isinstance(e.get("failure"), dict)
    ]


def _failure_counts(step: dict[str, Any]) -> dict[str, int]:
    """How many devices of a step failed per ``phase/kind`` (one count per device and kind)."""
    counts: Counter[str] = Counter()
    for envelope in ((step.get("output") or {}).get("outcomes") or {}).values():
        for device in (envelope.get("devices") or {}).values():
            kinds = {f"{f.get('phase')}/{f.get('kind')}" for f in _device_failures(device)}
            counts.update(kinds)
    return dict(counts)


def _step_summary(ctx: ToolContext, step: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "node_id": step.get("step_node_id"),
        "step_type": step.get("step_type"),
        "name": step.get("step_name"),
        "status": step.get("status"),
        "started_at": step.get("started_at"),
        "finished_at": step.get("finished_at"),
        "error_category": step.get("error_category"),
        "error_id": step.get("error_id"),
    }
    if isinstance(step.get("failure"), dict):
        summary["failure"] = step["failure"]
    failure_counts = _failure_counts(step)
    if failure_counts:
        summary["device_failures_by_cause"] = failure_counts
    if step.get("error_message"):
        summary["error_message"] = gated(ctx.sharing, DataClass.CONTENT, step["error_message"])
    return summary


def _group_summary(ctx: ToolContext, group: dict[str, Any]) -> dict[str, Any]:
    labeler = _state(ctx).labeler
    summary: dict[str, Any] = {
        "child_index": group["child_index"],
        "status": group["status"],
        "devices": [labeler.label(n) for n in group.get("device_names", [])],
        "node_states": group.get("node_states", {}),
    }
    if group.get("error_message"):
        summary["error_message"] = gated(ctx.sharing, DataClass.CONTENT, group["error_message"])
    return summary


def _device_summary(ctx: ToolContext, device: dict[str, Any], include: set[str]) -> dict[str, Any]:
    labeler = _state(ctx).labeler
    commands = [
        {
            "command": gated(ctx.sharing, DataClass.CONTENT, c.get("command")),
            "success": c.get("success"),
            "artifact_id": (c.get("output_ref") or {}).get("artifact_id"),
            "summary": gated(ctx.sharing, DataClass.CONTENT, c["summary"])
            if c.get("summary")
            else None,
        }
        for c in (device.get("command_results") or {}).values()
    ]
    out: dict[str, Any] = {
        "device": labeler.label(device.get("name") or device.get("id") or "unknown"),
        "status": device.get("status"),
        "capabilities": device.get("capabilities", []),
        "attribute_groups": sorted((device.get("attribute_bags") or {}).keys()),
        "parsed_keys": sorted((device.get("parsed") or {}).keys()),
        "commands": commands,
        "running_config_artifact": (device.get("running_config_ref") or {}).get("artifact_id"),
        "startup_config_artifact": (device.get("startup_config_ref") or {}).get("artifact_id"),
    }
    failures = _device_failures(device)
    if failures:
        out["failures"] = failures
    if device.get("errors"):
        out["errors"] = gated(ctx.sharing, DataClass.CONTENT, device["errors"])
    if "attributes" in include:
        out["attributes"] = gated(
            ctx.sharing,
            DataClass.INVENTORY,
            ctx.redactor.redact_data(
                mask_run_attributes(ctx.sharing, device.get("attribute_bags"))
            ),
        )
    if "parsed" in include:
        out["parsed"] = gated(
            ctx.sharing, DataClass.CONTENT, ctx.redactor.redact_data(device.get("parsed"))
        )
    return out


# -- handlers ---------------------------------------------------------------------------------


async def _get_run(ctx: ToolContext, args: RunRef) -> ToolOutput:
    run_id = _resolve_run_id(ctx, args.run_id)
    if run_id is None:
        return _NO_RUN
    try:
        run = await _load_run(ctx, run_id)
    except RunAccessError:
        return _NO_ACCESS
    summary: dict[str, Any] = {
        "id": run["id"],
        "workflow_id": run["workflow_id"],
        "status": run["status"],
        "trigger_type": run["trigger_type"],
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "paused_at_node": run.get("current_node_id"),
        "device_count": len(run.get("device_ids") or []),
        "error_category": run.get("error_category"),
        "error_id": run.get("error_id"),
        "run_inputs": gated(ctx.sharing, DataClass.CONTENT, run.get("run_inputs")),
        "steps": [_step_summary(ctx, s) for s in run.get("step_results", [])],
        "fan_out_groups": [_group_summary(ctx, g) for g in run.get("device_groups", [])],
    }
    if run.get("error_message"):
        summary["error_message"] = gated(ctx.sharing, DataClass.CONTENT, run["error_message"])
    return ToolOutput(_json(ctx.redactor.redact_data(summary)))


async def _get_step_result(ctx: ToolContext, args: StepResultInput) -> ToolOutput:
    run_id = _resolve_run_id(ctx, args.run_id)
    if run_id is None:
        return _NO_RUN
    state = _state(ctx)
    try:
        run = await _load_run(ctx, run_id)
    except RunAccessError:
        return _NO_ACCESS
    step = next(
        (s for s in run.get("step_results", []) if s.get("step_node_id") == args.node_id), None
    )
    if step is None:
        return ToolOutput(f"No result for step '{args.node_id}' in run {run_id}.", is_error=True)
    include = set(args.include)
    outcomes: dict[str, Any] = {}
    omitted = 0
    for outcome, envelope in ((step.get("output") or {}).get("outcomes") or {}).items():
        devices = [
            d
            for d in (envelope.get("devices") or {}).values()
            if args.device is None
            or state.labeler.matches(d.get("name") or d.get("id") or "", args.device)
        ]
        omitted += max(0, len(devices) - MAX_DEVICES_LISTED)
        outcomes[outcome] = [_device_summary(ctx, d, include) for d in devices[:MAX_DEVICES_LISTED]]
    result: dict[str, Any] = {"step": _step_summary(ctx, step), "outcomes": outcomes}
    if omitted:
        result["note"] = (
            f"{omitted} more device(s) not shown; pass 'device' to look at a specific one."
        )
    return ToolOutput(_json(ctx.redactor.redact_data(result)))


async def _get_artifact(ctx: ToolContext, args: ArtifactInput) -> ToolOutput:
    run_id = _resolve_run_id(ctx, args.run_id)
    if run_id is None:
        return _NO_RUN
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(_json(not_shared_marker(DataClass.CONTENT)))
    try:
        artifact = await _state(ctx).reader.get_artifact(run_id, args.artifact_id)
    except RunAccessError:
        return _NO_ACCESS
    if artifact is None:
        return ToolOutput(
            f"Artifact '{args.artifact_id}' not found in run {run_id}.", is_error=True
        )
    # Redact before truncating so a secret cut at the boundary cannot dodge the patterns.
    content = ctx.redactor.redact(str(artifact.get("content") or ""))
    truncated = len(content) > MAX_ARTIFACT_CHARS
    meta = {
        "artifact_id": artifact.get("artifact_id"),
        "kind": artifact.get("kind"),
        "size_bytes": artifact.get("size_bytes"),
        "truncated": truncated,
    }
    body = content[:MAX_ARTIFACT_CHARS] + (f"\n{TRUNCATION_NOTE}" if truncated else "")
    return ToolOutput(f"{json.dumps(meta)}\n<artifact>\n{body}\n</artifact>", truncated=truncated)


async def _list_events(ctx: ToolContext, args: EventsInput) -> ToolOutput:
    run_id = _resolve_run_id(ctx, args.run_id)
    if run_id is None:
        return _NO_RUN
    state = _state(ctx)
    try:
        await _load_run(ctx, run_id)  # seeds the device labels
        events = await state.reader.list_events(run_id, args.limit, args.node_id)
    except RunAccessError:
        return _NO_ACCESS
    rows = [
        {
            "step_node_id": e.get("step_node_id"),
            "device": state.labeler.label(e["device_name"]) if e.get("device_name") else None,
            "level": e.get("level"),
            "kind": e.get("kind"),
            "message": gated(ctx.sharing, DataClass.CONTENT, e.get("message")),
        }
        for e in events
    ]
    if not rows:
        return ToolOutput("No events recorded for this run.")
    return ToolOutput(_json(ctx.redactor.redact_data(rows)))


async def _get_run_workflow(ctx: ToolContext, args: RunRef) -> ToolOutput:
    run_id = _resolve_run_id(ctx, args.run_id)
    if run_id is None:
        return _NO_RUN
    try:
        workflow = await _state(ctx).reader.get_workflow(run_id)
    except RunAccessError:
        return _NO_ACCESS
    if workflow is None:
        return ToolOutput("The workflow of this run is not available to you.", is_error=True)
    view = build_compact_view(
        workflow["canvas_nodes"],
        workflow["canvas_edges"],
        workflow["static_attributes"],
        ctx.redactor,
    )
    return ToolOutput(
        _json(
            {
                "note": "Workflow as it is saved NOW; it may have changed since the run.",
                "name": ctx.redactor.redact(str(workflow["name"])),
                **view,
            }
        )
    )


RUN_VIEWER_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_run",
        "Run overview: status, timings, error category, every step with its status (failed steps "
        "show device_failures_by_cause, e.g. 'connect/timeout': 14), and fan-out device groups. "
        "Start here when explaining a failure.",
        RunRef,
        _get_run,
    ),
    Tool(
        "get_step_result",
        "What one step produced, per outcome and device: status, capabilities, commands with "
        "artifact ids, structured failures (phase, kind, attempts, elapsed_ms, hint; always "
        "available) and error text (needs the content opt-in). Pass include=['attributes'] or "
        "['parsed'] for data values.",
        StepResultInput,
        _get_step_result,
    ),
    Tool(
        "get_artifact",
        "Text of a stored artifact (command output, config backup) by artifact id from "
        "get_step_result. Needs the user's content-data opt-in; long output is truncated.",
        ArtifactInput,
        _get_artifact,
    ),
    Tool(
        "list_run_events",
        "Live events of the run (connection attempts, retries, auth failures), optionally for "
        "one step. The message text needs the user's content-data opt-in.",
        EventsInput,
        _list_events,
    ),
    Tool(
        "get_run_workflow",
        "The workflow definition this run belongs to (steps, config, edges), as saved now.",
        RunRef,
        _get_run_workflow,
    ),
)
