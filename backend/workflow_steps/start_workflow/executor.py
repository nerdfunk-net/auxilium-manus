"""Executor for the start-workflow workflow step.

Starts another workflow as a run of its own and optionally waits (bounded, at most
``_MAX_WAIT_SECONDS``) for it to finish. The typical use is "back up the running config before the
change".

Devices reach the started workflow the way a schedule or a manual run supplies them: through a
declared run input, the ``device_param`` of its Get from User step, filled with one ``name,ip``
line per device. A workflow without such an input is simply called without devices.

* ``run_mode: "all_devices"`` starts one run for all devices, so the step routes them together.
* ``run_mode: "per_device"`` starts one run per device (at most ``max_runs``, checked before
  anything is started) and routes every device by its own run.

A run counts as success when it finished successfully, the Get from User step that took the
devices really ran, and no step is failed, skipped or (unless ``allow_partial``) partial. A failed,
cancelled or partial run, or one still running when the wait budget ran out (it keeps running),
sends its devices through ``failure``. Without ``wait`` the step only starts the runs.

The wait is a plain bounded poll, not a Hatchet durable wait: a step executor has no access to
Hatchet's ``DurableContext`` (see doc/WORKFLOW-STEPS.md). All database work uses short sessions of
its own, in a thread, because the run's session is shared with concurrent branches.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from core.domain_exceptions import DomainError
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.nautobot.common.validators import validate_ip_address
from services.workflow.child_run_inputs import secret_input_message, secret_inputs_given
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.start_workflow.config import get_config

if TYPE_CHECKING:
    from services.execution.run_service import ChildRunSnapshot
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "start-workflow"
_MAX_WAIT_SECONDS = 600
_MIN_WAIT_SECONDS = 5
_MAX_POLL_SECONDS = 60
_MAX_RUNS_CEILING = 200
_RUN_MODES = ("all_devices", "per_device")
_DEVICE_INPUT_STEP_KIND = "get-from-user"


@dataclass(frozen=True)
class _ParsedConfig:
    workflow_id: int
    run_inputs: dict[str, Any]
    devices_input: str
    per_device: bool
    max_runs: int
    wait: bool
    wait_seconds: int
    poll_interval_seconds: int
    allow_partial: bool
    bag_name: str


def _parse_workflow_id(config: dict[str, Any]) -> int:
    raw_id = config.get("workflow_id")
    try:
        workflow_id = int(raw_id) if raw_id not in (None, "") else 0
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_STEP_ID}: workflow_id must be a workflow id") from exc
    if workflow_id < 1:
        raise ValueError(f"{_STEP_ID}: select the workflow to start (workflow_id)")
    return workflow_id


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    workflow_id = _parse_workflow_id(config)

    run_inputs = config.get("run_inputs") or {}
    if not isinstance(run_inputs, dict):
        raise ValueError(f"{_STEP_ID}: run_inputs must be an object of input name to value")

    run_mode = str(config.get("run_mode") or defaults["run_mode"]).strip()
    if run_mode not in _RUN_MODES:
        raise ValueError(f"{_STEP_ID}: run_mode must be one of {', '.join(_RUN_MODES)}")
    devices_input = str(config.get("devices_input") or "").strip()
    if run_mode == "per_device" and not devices_input:
        raise ValueError(f"{_STEP_ID}: one run per device needs devices_input to put the device in")

    try:
        wait = parse_bool_flag(config, "wait", default=defaults["wait"])
        allow_partial = parse_bool_flag(config, "allow_partial", default=defaults["allow_partial"])
        wait_seconds = parse_int_flag(
            config,
            "wait_seconds",
            default=defaults["wait_seconds"],
            minimum=_MIN_WAIT_SECONDS,
            maximum=_MAX_WAIT_SECONDS,
        )
        poll_interval = parse_int_flag(
            config,
            "poll_interval_seconds",
            default=defaults["poll_interval_seconds"],
            minimum=1,
            maximum=_MAX_POLL_SECONDS,
        )
        max_runs = parse_int_flag(
            config,
            "max_runs",
            default=defaults["max_runs"],
            minimum=1,
            maximum=_MAX_RUNS_CEILING,
        )
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    bag_name = str(config.get("bag_name") or defaults["bag_name"]).strip() or defaults["bag_name"]
    return _ParsedConfig(
        workflow_id=workflow_id,
        run_inputs=dict(run_inputs),
        devices_input=devices_input,
        per_device=run_mode == "per_device",
        max_runs=max_runs,
        wait=wait,
        wait_seconds=wait_seconds,
        poll_interval_seconds=poll_interval,
        allow_partial=allow_partial,
        bag_name=bag_name,
    )


# ── what the started workflow is told about the devices ───────────────────────────────────────


def _device_line(device: DeviceContext) -> str | None:
    """One ``name,ip`` line for Get from User, or None when the device has no usable identity.

    A name that would break the line format (a comma or a line break) is left out; the bare
    primary IP stands in for it.
    """
    name = (device.name or "").strip()
    if not name or "," in name or len(name.splitlines()) != 1:
        name = ""
    ip = bare_hostname(device.primary_ip4, "").strip()
    if ip and not validate_ip_address(ip):
        ip = ""
    if name and ip:
        return f"{name},{ip}"
    return name or ip or None


# ── the started workflow, inspected ─────────────────────────────────────────────────────────────


def _inspect_target(
    workflow_name: str,
    nodes: list[Any],
    static_attributes: list[dict[str, Any]] | None,
    run_inputs: dict[str, Any],
    devices_input: str,
) -> list[str]:
    """Ids of the enabled steps of the target that take ``devices_input``.

    Raises ``ValueError`` when the input is not a declared text input read by such a step (the
    devices would never arrive), when ``run_inputs`` also gives it a value, or when ``run_inputs``
    gives a secret input (it would be stored in the definition). Author-disabled steps are removed
    from the graph before a run, so they do not count. Without ``devices_input`` no step is
    required and the result is empty.
    """
    secrets = secret_inputs_given(run_inputs, static_attributes)
    if secrets:
        raise ValueError(f"{_STEP_ID}: {secret_input_message(_STEP_ID, workflow_name, secrets)}")
    if not devices_input:
        return []
    declared = next(
        (
            attr
            for attr in static_attributes or []
            if isinstance(attr, dict) and attr.get("name") == devices_input
        ),
        None,
    )
    if declared is None or declared.get("type") != "string":
        raise ValueError(
            f"{_STEP_ID}: workflow {workflow_name!r} has no text run input {devices_input!r}"
        )
    if devices_input in run_inputs:
        raise ValueError(
            f"{_STEP_ID}: {devices_input!r} receives this workflow's devices; "
            "remove it from run_inputs"
        )
    readers = [
        str(node["id"])
        for node in nodes
        if isinstance(node, dict)
        and node.get("id") is not None
        and (node.get("data") or {}).get("disabled") is not True
        and (node.get("data") or {}).get("kind") == _DEVICE_INPUT_STEP_KIND
        and ((node.get("data") or {}).get("pluginConfig") or {}).get("device_param")
        == devices_input
    ]
    if not readers:
        raise ValueError(
            f"{_STEP_ID}: workflow {workflow_name!r} has no enabled 'Get from User' step that "
            f"reads the run input {devices_input!r}, so it would not act on this workflow's devices"
        )
    return readers


# ── database seams (each opens a short session of its own and runs in a thread) ───────────────


def _check_target_sync(
    parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any], devices_input: str
) -> list[str]:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise ValueError(f"{_STEP_ID}: the calling run no longer exists")
        workflow = RunService(db).require_child_target(parent, workflow_id)
        return _inspect_target(
            workflow.name,
            list(workflow.canvas_nodes or []),
            list(workflow.static_attributes or []),
            run_inputs,
            devices_input,
        )


def _start_child_sync(parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any]) -> int:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(parent_run_id)
        if parent is None:
            raise ValueError(f"{_STEP_ID}: the calling run no longer exists")
        return RunService(db).start_child_run(parent, workflow_id, run_inputs=run_inputs).id


def _snapshot_sync(run_id: int) -> ChildRunSnapshot:
    from core.database import SessionLocal
    from services.execution.run_service import RunService

    with SessionLocal() as db:
        return RunService(db).child_run_snapshot(run_id)


def _parent_cancelled_sync(run_id: int) -> bool:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        parent = RunRepository(db).get_run(run_id)
        if parent is None:
            return True
        db.refresh(parent)
        return parent.status == "cancelled"


async def _check_target(
    *, parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any], devices_input: str
) -> list[str]:
    return await asyncio.to_thread(
        _check_target_sync, parent_run_id, workflow_id, run_inputs, devices_input
    )


async def _start_child(*, parent_run_id: int, workflow_id: int, run_inputs: dict[str, Any]) -> int:
    return await asyncio.to_thread(_start_child_sync, parent_run_id, workflow_id, run_inputs)


async def _snapshot(run_id: int) -> ChildRunSnapshot:
    return await asyncio.to_thread(_snapshot_sync, run_id)


async def _parent_cancelled(run_id: int) -> bool:
    return await asyncio.to_thread(_parent_cancelled_sync, run_id)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


# ── runs and their results ──────────────────────────────────────────────────────────────────────


@dataclass
class _Group:
    """Devices that share one started run."""

    device_keys: list[str]
    text: str | None
    run_id: int | None = None
    status: str = "not_started"
    waited: int = 0
    code: str = ""
    message: str = ""
    failure: FailureInfo | None = None
    accepted: bool = False
    finished: bool = field(default=False, repr=False)

    def reject(
        self, code: str, message: str, failure: FailureInfo, *, status: str, waited: int
    ) -> None:
        self.accepted = False
        self.finished = True
        self.code, self.message, self.failure = code, message, failure
        self.status, self.waited = status, waited


def _judge(
    snapshot: ChildRunSnapshot, parsed: _ParsedConfig, readers: list[str]
) -> tuple[bool, str, str]:
    """(accepted, code, message) for a finished child run."""
    if snapshot.status != "success":
        return (
            False,
            f"child_run_{snapshot.status}",
            f"run {snapshot.run_id} ended with status {snapshot.status}",
        )
    # A run can end "success" without ever working on the devices (the step that takes them was
    # disabled, unreachable or skipped): that is no backup.
    if readers and not any(snapshot.step_statuses.get(node) == "success" for node in readers):
        return (
            False,
            "child_run_not_applied",
            f"run {snapshot.run_id} finished, but its step that takes the devices did not run",
        )
    worst = snapshot.worst_step_status
    if worst in ("failed", "skipped") or (worst == "partial" and not parsed.allow_partial):
        return (
            False,
            "child_run_partial",
            f"run {snapshot.run_id} finished, but a step did not succeed for every device",
        )
    return True, "", ""


def _build_groups(
    parsed: _ParsedConfig, eligible: dict[str, DeviceContext], lines: dict[str, str]
) -> list[_Group]:
    if not parsed.devices_input:
        return [_Group(device_keys=list(eligible), text=None)]
    if parsed.per_device:
        return [_Group(device_keys=[key], text=lines[key]) for key in eligible]
    return [_Group(device_keys=list(eligible), text="\n".join(lines[key] for key in eligible))]


def _engine_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="server_error", retryable=True)


async def _start_groups(parsed: _ParsedConfig, groups: list[_Group], *, parent_run_id: int) -> None:
    """Start one run per group; an unreachable engine fails this and every later group."""
    engine_down = False
    for group in groups:
        if engine_down:
            group.reject(
                "engine_unavailable",
                "the workflow execution engine is unavailable; nothing was started",
                _engine_failure(),
                status="not_started",
                waited=0,
            )
            continue
        run_inputs = dict(parsed.run_inputs)
        if parsed.devices_input and group.text is not None:
            run_inputs[parsed.devices_input] = group.text
        try:
            group.run_id = await _start_child(
                parent_run_id=parent_run_id, workflow_id=parsed.workflow_id, run_inputs=run_inputs
            )
            group.status = "dispatched"
        except HTTPException:
            engine_down = True
            group.reject(
                "engine_unavailable",
                "the workflow execution engine is unavailable; nothing was started",
                _engine_failure(),
                status="not_started",
                waited=0,
            )
        except DomainError as exc:
            # Not allowed / not found / recursion / bad run inputs: a configuration problem.
            raise ValueError(f"{_STEP_ID}: {exc}") from exc


async def _wait_for_groups(
    parsed: _ParsedConfig, groups: list[_Group], readers: list[str], *, parent_run_id: int
) -> None:
    pending = [g for g in groups if g.run_id is not None and not g.finished]
    waited = 0
    while pending:
        snapshots = await asyncio.gather(*(_snapshot(int(g.run_id or 0)) for g in pending))
        still: list[_Group] = []
        for group, snapshot in zip(pending, snapshots, strict=True):
            if snapshot.is_terminal:
                group.accepted, group.code, group.message = _judge(snapshot, parsed, readers)
                group.status, group.waited, group.finished = snapshot.status, waited, True
                if not group.accepted:
                    group.failure = FailureInfo(
                        phase="task", kind="task_failed", elapsed_ms=waited * 1000
                    )
            else:
                still.append(group)
        pending = still
        if not pending:
            return
        if await _parent_cancelled(parent_run_id):
            for group in pending:
                group.reject(
                    "calling_run_cancelled",
                    f"the calling run was cancelled while waiting for run {group.run_id}",
                    FailureInfo(phase="task", kind="task_failed", elapsed_ms=waited * 1000),
                    status="cancelled_parent",
                    waited=waited,
                )
            return
        if waited >= parsed.wait_seconds:
            for group in pending:
                group.reject(
                    "child_run_timeout",
                    f"run {group.run_id} was still running after {waited} s; it keeps running "
                    "in the background",
                    FailureInfo(
                        phase="task", kind="task_timeout", retryable=True, elapsed_ms=waited * 1000
                    ),
                    status="timeout",
                    waited=waited,
                )
            return
        step = min(parsed.poll_interval_seconds, parsed.wait_seconds - waited)
        await _sleep(step)
        waited += step


# ── outcome assembly ────────────────────────────────────────────────────────────────────────


def _with_bag(device: DeviceContext, parsed: _ParsedConfig, group: _Group) -> DeviceContext:
    bag = {
        "run_id": group.run_id,
        "workflow_id": parsed.workflow_id,
        "status": group.status,
        "waited_seconds": group.waited,
    }
    return device.model_copy(
        update={"attribute_bags": {**device.attribute_bags, parsed.bag_name: bag}}
    )


def _assemble(
    context: WorkflowContext,
    parsed: _ParsedConfig,
    groups: list[_Group],
    no_identity: dict[str, DeviceContext],
    *,
    node_id: str,
) -> list[StepOutcome]:
    ok: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = dict(no_identity)
    first_failure: FailureInfo | None = None
    for group in groups:
        for key in group.device_keys:
            device = context.devices[key]
            if group.run_id is not None:
                device = _with_bag(device, parsed, group)
            if group.accepted or (not group.finished and group.run_id is not None):
                ok[key] = device
                continue
            first_failure = first_failure or group.failure
            failed[key] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=_STEP_ID,
                code=group.code,
                message=group.message,
                failure=group.failure,
            )
    outcomes: list[StepOutcome] = []
    if ok or not failed:
        outcomes.append(
            StepOutcome(
                name="success",
                context=context.model_copy(update={"devices": ok}),
                summary=f"{len(ok)} device(s) passed, {len(failed)} failed",
            )
        )
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed}),
                failure=None if ok else first_failure,
            )
        )
    return outcomes


def _split_by_identity(
    parsed: _ParsedConfig, context: WorkflowContext, *, node_id: str
) -> tuple[dict[str, DeviceContext], dict[str, str], dict[str, DeviceContext]]:
    """(devices to hand over, their lines, devices that cannot be named to the other workflow)."""
    if not parsed.devices_input:
        return dict(context.devices), {}, {}
    eligible: dict[str, DeviceContext] = {}
    lines: dict[str, str] = {}
    no_identity: dict[str, DeviceContext] = {}
    for key, device in context.devices.items():
        line = _device_line(device)
        if line is None:
            no_identity[key] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=_STEP_ID,
                code="no_device_identity",
                message="the device has no name or IP address the started workflow can use",
                failure=FailureInfo(phase="internal", kind="bad_request"),
            )
        else:
            eligible[key] = device
            lines[key] = line
    return eligible, lines, no_identity


# ── execute ────────────────────────────────────────────────────────────────────────────────


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: no artifacts, no SSH sessions

    parsed = _parse_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    eligible, lines, no_identity = _split_by_identity(parsed, context, node_id=node_id)
    if not eligible:
        return _assemble(context, parsed, [], no_identity, node_id=node_id)

    groups = _build_groups(parsed, eligible, lines)
    if len(groups) > parsed.max_runs:
        raise ValueError(
            f"{_STEP_ID}: this step would start {len(groups)} runs, more than max_runs "
            f"({parsed.max_runs}); raise max_runs or start one run for all devices"
        )

    logger.info(
        "%s started run_id=%s node_id=%s workflow_id=%d runs=%d devices=%d wait=%s",
        _STEP_ID,
        run.id,
        node_id,
        parsed.workflow_id,
        len(groups),
        len(eligible),
        parsed.wait,
    )
    try:
        readers = await _check_target(
            parent_run_id=run.id,
            workflow_id=parsed.workflow_id,
            run_inputs=parsed.run_inputs,
            devices_input=parsed.devices_input,
        )
    except DomainError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    await _start_groups(parsed, groups, parent_run_id=run.id)
    if parsed.wait:
        await _wait_for_groups(parsed, groups, readers, parent_run_id=run.id)

    outcomes = _assemble(context, parsed, groups, no_identity, node_id=node_id)
    logger.info(
        "%s finished run_id=%s runs=%d outcomes=%s",
        _STEP_ID,
        run.id,
        len(groups),
        ",".join(o.name for o in outcomes),
    )
    return outcomes
