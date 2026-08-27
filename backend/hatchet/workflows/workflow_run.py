from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from hatchet_sdk import Context, DurableContext
from pydantic import BaseModel

from hatchet.client import hatchet
from hatchet.workflows.device_group_execution import DeviceGroupInput, child_workflow
from services.execution.run_events import (
    STEP_EVENT_LOOKBACK,
    batch_approval_event_key,
    debug_step_event_key,
)

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

    from models.workflow_context import WorkflowContext

logger = logging.getLogger(__name__)

# Cap on how many device names are stamped into WorkflowRun.approval_state —
# it's a UI display hint, not a source of truth (the real device set lives in
# the child WorkflowContext), so an unbounded list would just bloat the row.
MAX_APPROVAL_STATE_DEVICE_NAMES = 25


class WorkflowRunInput(BaseModel):
    run_id: int


async def prepare(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Preparing workflow run run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        repo = RunRepository(db)
        result = repo.get_run_by_id(input.run_id)
        if result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = result
        repo.update_run_status(
            run,
            status="running",
            started_at=datetime.now(UTC),
        )

    return {"run_id": input.run_id}


async def _maybe_debug_pause_before_node(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    node: dict[str, Any],
    ctx: DurableContext,
) -> Any:
    if run.run_mode != "debug":
        return run

    node_id: str = node.get("id", "")
    node_title = (node.get("data", {}) or {}).get("title", node_id)
    run_repo.update_run_status(
        run,
        status="paused",
        current_node_id=node_id,
        debug_message=(
            f"Paused before '{node_title}' (node {node_id}). Click Next Step to continue."
        ),
    )
    event_key = debug_step_event_key(run.uuid, node_id)
    logger.info("Debug pause run_id=%s node_id=%s", run.id, node_id)
    # Devices drop idle SSH long before a debug pause can resume — release
    # live sessions now; the next network step reconnects lazily.
    await runner.suspend_device_sessions()
    await ctx.aio_wait_for_event(
        event_key,
        scope=event_key,
        lookback_window=STEP_EVENT_LOOKBACK,
    )

    # Force a refresh — a "Run to completion" click (a separate DB
    # session/request) may have flipped run_mode while we waited.
    # A plain re-select would return this same identity-mapped object
    # without re-reading already-loaded columns from the DB.
    run_repo.db.refresh(run)
    if run.run_mode == "debug":
        run_repo.update_run_status(
            run,
            status="running",
            debug_message=f"Resumed. Executing '{node_title}'.",
        )
    else:
        run_repo.update_run_status(run, status="running")
    return run


def _fan_out_context_if_requested(
    *,
    node_id: str,
    step_outcomes: dict[str, dict[str, Any]],
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    run_id: int,
) -> dict[str, Any] | None:
    from services.execution.graph import find_join_node_id
    from services.execution.step_runner import FanOutSignal

    success_ctx = step_outcomes.get(node_id, {}).get("success")
    if not (success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled")):
        return None

    fan_out_config = dict(success_ctx.metadata["_fan_out"])
    join_node_id = find_join_node_id(node_id, canvas_nodes, canvas_edges)
    logger.info(
        "Fan-out requested node_id=%s mode=%s join_node_id=%s run_id=%s",
        node_id,
        fan_out_config.get("mode"),
        join_node_id,
        run_id,
    )
    signal = FanOutSignal(
        inventory_node_id=node_id,
        fan_out_config=fan_out_config,
        inventory_outcome=success_ctx,
        step_outcomes=dict(step_outcomes),
        join_node_id=join_node_id,
    )
    return {
        "signal": signal,
        "canvas_nodes": canvas_nodes,
        "canvas_edges": canvas_edges,
    }


async def _run_steps_until_fan_out_or_done(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    wf: Any,
    ctx: DurableContext,
) -> tuple[Any, dict[str, Any] | None, Any]:
    """Walk nodes in topological order, executing one at a time.

    In debug mode (``run.run_mode == "debug"``), durably waits for a
    ``workflow-run.{uuid}.step.{node_id}`` event before executing each node —
    this is the "Next Step" gate. In normal mode this behaves exactly like the
    previous ``StepRunner.execute_all`` in-one-shot walk.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the (possibly reloaded, e.g. after a debug resume) WorkflowRun to keep
    using in the caller.
    """
    canvas_nodes, canvas_edges = runner.load_execution_graph(wf)
    ordered_nodes = runner.build_execution_plan(canvas_nodes, canvas_edges)
    step_results = runner.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

    step_outcomes: dict[str, dict[str, Any]] = {}
    blocked_nodes: set[str] = set()
    failed = False
    any_reported_failure = False

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        step_result = step_results[node_id]

        if failed:
            run_repo.update_step_result(step_result, status="skipped")
            continue

        run = await _maybe_debug_pause_before_node(
            run_repo=run_repo, runner=runner, run=run, node=node, ctx=ctx
        )

        raised, indicates_failure = await runner.run_node_in_sequence(
            node=node,
            run=run,
            workflow=wf,
            edges=canvas_edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
            blocked_nodes=blocked_nodes,
        )
        if raised:
            failed = True
            continue
        if indicates_failure:
            any_reported_failure = True

        fan_out = _fan_out_context_if_requested(
            node_id=node_id,
            step_outcomes=step_outcomes,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            run_id=run.id,
        )
        if fan_out is not None:
            return None, fan_out, run

    return ("success" if not (failed or any_reported_failure) else "failed"), None, run


async def _debug_pause_before_fan_out(
    *,
    run: Any,
    run_repo: Any,
    signal: Any,
    ctx: DurableContext,
) -> None:
    fan_out_label = signal.join_node_id or signal.inventory_node_id
    run_repo.update_run_status(
        run,
        status="paused",
        current_node_id=fan_out_label,
        debug_message=(
            "Paused before fan-out dispatch. Click Next Step to run all "
            "device groups and the fan-in join as one block."
        ),
    )
    event_key = debug_step_event_key(run.uuid, fan_out_label)
    logger.info("Debug pause (fan-out) run_id=%s node_id=%s", run.id, fan_out_label)
    await ctx.aio_wait_for_event(
        event_key,
        scope=event_key,
        lookback_window=STEP_EVENT_LOOKBACK,
    )

    run_repo.db.refresh(run)
    run_repo.update_run_status(run, status="running")


async def _phase1_run_or_early_finish(
    *,
    run_id: int,
    ctx: DurableContext,
    SessionLocal: Any,
    RunRepository: Any,
    WorkflowRepository: Any,
    StepRunner: Any,
) -> dict[str, Any] | tuple[str, Any, list[dict[str, Any]], list[dict[str, Any]]]:
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {run_id} not found")
        run, _ = run_result
        # Captured now — the phase-1 DB session closes before phase 2 dispatch.
        run_uuid = run.uuid

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        runner = StepRunner(db)
        try:
            final_status, fan_out, run = await _run_steps_until_fan_out_or_done(
                run_repo=run_repo, runner=runner, run=run, wf=wf, ctx=ctx
            )
        finally:
            # Close (not suspend) here: on the fan-out path, children build their
            # own pools and phase 2/3 hold no device connections — this also runs
            # before the fan-out debug pause below.
            await runner.close_device_sessions()

        if fan_out is None:
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(UTC),
            )
            logger.info("Run finished run_id=%s status=%s", run_id, final_status)
            return {"run_id": run_id, "status": final_status}

        signal = fan_out["signal"]
        canvas_nodes: list[dict[str, Any]] = fan_out["canvas_nodes"]
        canvas_edges: list[dict[str, Any]] = fan_out["canvas_edges"]

        # Fan-out runs as one atomic step in debug mode: pause once before
        # dispatching children; the join and everything downstream of it then
        # run in a single block on the next step/continue click (no per-device
        # or per-post-join-node pausing — see doc/WORKFLOW-STEPS.md fan-out
        # notes on why children can't be stepped individually).
        if run.run_mode == "debug":
            await _debug_pause_before_fan_out(
                run=run,
                run_repo=run_repo,
                signal=signal,
                ctx=ctx,
            )

    return run_uuid, signal, canvas_nodes, canvas_edges


async def _finalize_fan_out_parent(
    *,
    run_id: int,
    signal: Any,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    child_results: list[dict[str, Any] | BaseException],
    SessionLocal: Any,
    RunRepository: Any,
    WorkflowRepository: Any,
    StepRunner: Any,
) -> str:
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {run_id} not found (phase 3)")
        run, _ = run_result

        success, child_merged = _aggregate_and_persist(
            run_repo=run_repo,
            run_id=run.id,
            signal=signal,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            child_results=child_results,
        )

        # Phase 4: when a fan-in node exists, resume execution once on the merged
        # (fanned-in) context so git/store steps after the join run exactly once.
        if signal.join_node_id is not None:
            wf_result = wf_repo.get_by_id(run.workflow_id)
            if wf_result is None:
                raise ValueError(f"Workflow {run.workflow_id} not found (phase 4 resume)")
            wf, _ = wf_result

            # The fan-in node's parents are child-branch nodes; the inventory
            # node is included so a join wired directly to it still resolves.
            merged_outcomes: dict[str, dict[str, Any]] = {
                signal.inventory_node_id: {"success": signal.inventory_outcome}
            }
            merged_outcomes.update(child_merged)

            logger.info(
                "Fan-in resume run_id=%s join_node_id=%s",
                run_id,
                signal.join_node_id,
            )
            post_join_runner = StepRunner(db)
            try:
                join_success = await post_join_runner.resume_after_join(
                    run=run,
                    workflow=wf,
                    merged_outcomes=merged_outcomes,
                    join_node_id=signal.join_node_id,
                )
            finally:
                await post_join_runner.close_device_sessions()
            success = success and join_success

        final_status = "success" if success else "failed"
        run_repo.update_run_status(
            run,
            status=final_status,
            finished_at=datetime.now(UTC),
        )

    return final_status


async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    early = await _phase1_run_or_early_finish(
        run_id=input.run_id,
        ctx=ctx,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    if isinstance(early, dict):
        return early

    run_uuid, signal, canvas_nodes, canvas_edges = early

    logger.info(
        "Fan-out started run_id=%s mode=%s max_concurrency=%s",
        input.run_id,
        signal.fan_out_config.get("mode"),
        signal.fan_out_config.get("max_concurrency"),
    )
    child_results = await _dispatch_children(
        signal,
        input.run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
    )

    final_status = await _finalize_fan_out_parent(
        run_id=input.run_id,
        signal=signal,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
        child_results=child_results,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    logger.info("Run finished (fan-out) run_id=%s status=%s", input.run_id, final_status)
    return {"run_id": input.run_id, "status": final_status}


def build_workflow_execution(
    *, name: str, concurrency: int | None = None
) -> HatchetWorkflow[WorkflowRunInput]:
    """Construct one Hatchet workflow with the standard prepare -> execute_steps
    shape, attaching the shared task implementations above. Used both for the
    single static WorkflowExecution registration below and, per published
    background-tier row, by hatchet/dynamic_worker.py — zero duplicated
    business logic either way, since prepare/execute_steps here are the same
    plain async functions in both cases, just registered under a different
    workflow name/concurrency limit.
    """
    wf = hatchet.workflow(
        name=name,
        on_events=["workflow:run"] if name == "WorkflowExecution" else None,
        input_validator=WorkflowRunInput,
        concurrency=concurrency,
    )
    prepare_task = wf.task(name="prepare", execution_timeout=timedelta(seconds=30))(prepare)
    wf.durable_task(
        name="execute_steps", parents=[prepare_task], execution_timeout=timedelta(hours=24)
    )(execute_steps)
    return wf


# Static registration — unchanged for every existing importer
# (`from hatchet.workflows.workflow_run import workflow as workflow_execution`).
workflow = build_workflow_execution(name="WorkflowExecution")


def _build_approval_state(
    *,
    awaiting: bool,
    next_batch_index: int,
    total_batches: int,
    batches_completed: int,
    devices_total: int,
    devices_completed: int,
    devices_failed: int,
    next_batch_device_names: list[str],
    auto_approve_remaining: bool = False,
) -> dict[str, Any]:
    """Build the WorkflowRun.approval_state shape documented in doc/WAIT-AND-RUN.md §5.2."""
    return {
        "awaiting": awaiting,
        "next_batch_index": next_batch_index,
        "total_batches": total_batches,
        "batches_completed": batches_completed,
        "devices_total": devices_total,
        "devices_completed": devices_completed,
        "devices_failed": devices_failed,
        "next_batch_device_names": next_batch_device_names[:MAX_APPROVAL_STATE_DEVICE_NAMES],
        "auto_approve_remaining": auto_approve_remaining,
    }


def _format_approval_pause_message(
    *,
    batches_completed: int,
    total_batches: int,
    devices_completed: int,
    devices_failed: int,
    next_batch_index: int,
    next_batch_device_names: list[str],
) -> str:
    if batches_completed == 0:
        prefix = f"Ready to run batch {next_batch_index + 1}/{total_batches}."
    else:
        devices_ok = devices_completed - devices_failed
        prefix = (
            f"Batch {batches_completed}/{total_batches} finished "
            f"({devices_ok} device(s) ok, {devices_failed} failed)."
        )

    preview_names = next_batch_device_names[:10]
    names_preview = ", ".join(preview_names)
    if len(next_batch_device_names) > len(preview_names):
        names_preview += ", …"

    return (
        f"{prefix} Waiting for approval to run batch {next_batch_index + 1} "
        f"({len(next_batch_device_names)} device(s): {names_preview}). "
        'Click "Run next batch" to continue or Cancel to stop.'
    )


@dataclass(frozen=True)
class _FanOutDispatchPlan:
    groups: list[list[str]]
    max_concurrency: int
    approval_enabled: bool
    approval_cfg: dict[str, Any]
    device_ids: list[str]
    all_devices: dict[str, Any]


def _parse_fan_out_dispatch(signal: Any) -> _FanOutDispatchPlan:
    from services.execution.step_runner import FanOutSignal

    assert isinstance(signal, FanOutSignal)

    fan_out_config = signal.fan_out_config
    mode = fan_out_config.get("mode", "per_device")
    chunk_size = max(1, int(fan_out_config.get("chunk_size", 1)))
    max_concurrency = max(0, int(fan_out_config.get("max_concurrency", 0)))
    approval_cfg: dict[str, Any] = fan_out_config.get("approval") or {}
    approval_enabled = bool(approval_cfg.get("enabled"))

    all_devices = signal.inventory_outcome.devices
    device_ids = list(all_devices.keys())

    if mode == "chunked":
        groups = [device_ids[i : i + chunk_size] for i in range(0, len(device_ids), chunk_size)]
    else:
        groups = [[did] for did in device_ids]

    return _FanOutDispatchPlan(
        groups=groups,
        max_concurrency=max_concurrency,
        approval_enabled=approval_enabled,
        approval_cfg=approval_cfg,
        device_ids=device_ids,
        all_devices=all_devices,
    )


def _build_child_inputs(
    signal: Any,
    *,
    parent_run_id: int,
    all_devices: dict[str, Any],
    group_list: list[list[str]],
    index_offset: int,
) -> list[DeviceGroupInput]:
    inputs: list[DeviceGroupInput] = []
    for offset, group_ids in enumerate(group_list):
        group_devices = {did: all_devices[did] for did in group_ids}
        group_context = signal.inventory_outcome.model_copy(update={"devices": group_devices})
        inputs.append(
            DeviceGroupInput(
                parent_run_id=parent_run_id,
                context_json=group_context.model_dump_json(),
                start_node_id=signal.inventory_node_id,
                child_index=index_offset + offset,
                join_node_id=signal.join_node_id,
            )
        )
    return inputs


async def _run_groups(
    signal: Any,
    *,
    parent_run_id: int,
    all_devices: dict[str, Any],
    max_concurrency: int,
    group_list: list[list[str]],
    index_offset: int,
) -> list[dict[str, Any] | BaseException]:
    child_inputs = _build_child_inputs(
        signal,
        parent_run_id=parent_run_id,
        all_devices=all_devices,
        group_list=group_list,
        index_offset=index_offset,
    )

    if max_concurrency <= 0:
        tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(inp: DeviceGroupInput) -> dict[str, Any]:
        async with semaphore:
            return await child_workflow.aio_run(inp)

    tasks = [_run_one(inp) for inp in child_inputs]
    return list(await asyncio.gather(*tasks, return_exceptions=True))


def _tally_batch_failures(
    batch_groups: list[list[str]],
    batch_results: list[dict[str, Any] | BaseException],
) -> tuple[int, int]:
    batch_device_count = sum(len(group) for group in batch_groups)
    batch_failed_count = sum(
        len(group)
        for group, result in zip(batch_groups, batch_results, strict=True)
        if isinstance(result, BaseException)
    )
    return batch_device_count, batch_failed_count


def _batch_needs_approval_gate(
    *,
    batch_index: int,
    first_batch_auto: bool,
    auto_approve_remaining: bool,
) -> bool:
    return not auto_approve_remaining and not (batch_index == 0 and first_batch_auto)


def _device_names_for_groups(
    plan: _FanOutDispatchPlan,
    batch_groups: list[list[str]],
) -> list[str]:
    return [plan.all_devices[did].name for group in batch_groups for did in group]


async def _wait_and_resume_batch_approval(
    *,
    signal: Any,
    parent_run_id: int,
    ctx: DurableContext,
    run_uuid: str,
    batch_index: int,
    total_batches: int,
    devices_completed: int,
    devices_failed: int,
    batch_device_names: list[str],
    devices_total: int,
    SessionLocal: Any,
    RunRepository: Any,
) -> bool:
    state = _build_approval_state(
        awaiting=True,
        next_batch_index=batch_index,
        total_batches=total_batches,
        batches_completed=batch_index,
        devices_total=devices_total,
        devices_completed=devices_completed,
        devices_failed=devices_failed,
        next_batch_device_names=batch_device_names,
    )
    message = _format_approval_pause_message(
        batches_completed=batch_index,
        total_batches=total_batches,
        devices_completed=devices_completed,
        devices_failed=devices_failed,
        next_batch_index=batch_index,
        next_batch_device_names=batch_device_names,
    )

    with SessionLocal() as db:
        run_repo = RunRepository(db)
        run_result = run_repo.get_run_by_id(parent_run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {parent_run_id} not found (approval gate)")
        run, _ = run_result
        run_repo.update_run_status(
            run,
            status="paused",
            current_node_id=signal.inventory_node_id,
            debug_message=message,
            approval_state=state,
        )

    event_key = batch_approval_event_key(run_uuid, batch_index)
    logger.info(
        "Approval pause run_id=%s batch=%d/%d",
        parent_run_id,
        batch_index + 1,
        total_batches,
    )
    await ctx.aio_wait_for_event(
        event_key, scope=event_key, lookback_window=STEP_EVENT_LOOKBACK
    )

    with SessionLocal() as db:
        run_repo = RunRepository(db)
        run_result = run_repo.get_run_by_id(parent_run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {parent_run_id} not found (approval resume)")
        run, _ = run_result
        auto_approve_remaining = bool(
            (run.approval_state or {}).get("auto_approve_remaining")
        )
        run_repo.update_run_status(
            run,
            status="running",
            approval_state={**(run.approval_state or {}), "awaiting": False},
        )
    return auto_approve_remaining


async def _dispatch_with_approval(
    signal: Any,
    *,
    parent_run_id: int,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    plan: _FanOutDispatchPlan,
) -> list[dict[str, Any] | BaseException]:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    approval_cfg = plan.approval_cfg
    batch_size = max(1, int(approval_cfg.get("batch_size", 1)))
    first_batch_auto = bool(approval_cfg.get("first_batch_auto", True))
    batches = [plan.groups[i : i + batch_size] for i in range(0, len(plan.groups), batch_size)]
    total_batches = len(batches)

    all_results: list[dict[str, Any] | BaseException] = []
    auto_approve_remaining = False
    devices_completed = 0
    devices_failed = 0
    group_index_offset = 0

    for batch_index, batch_groups in enumerate(batches):
        if _batch_needs_approval_gate(
            batch_index=batch_index,
            first_batch_auto=first_batch_auto,
            auto_approve_remaining=auto_approve_remaining,
        ):
            auto_approve_remaining = await _wait_and_resume_batch_approval(
                signal=signal,
                parent_run_id=parent_run_id,
                ctx=ctx,
                run_uuid=run_uuid,
                batch_index=batch_index,
                total_batches=total_batches,
                devices_completed=devices_completed,
                devices_failed=devices_failed,
                batch_device_names=_device_names_for_groups(plan, batch_groups),
                devices_total=len(plan.device_ids),
                SessionLocal=SessionLocal,
                RunRepository=RunRepository,
            )

        batch_results = await _run_groups(
            signal,
            parent_run_id=parent_run_id,
            all_devices=plan.all_devices,
            max_concurrency=plan.max_concurrency,
            group_list=batch_groups,
            index_offset=group_index_offset,
        )
        group_index_offset += len(batch_groups)
        all_results.extend(batch_results)

        batch_device_count, batch_failed_count = _tally_batch_failures(
            batch_groups, batch_results
        )
        devices_completed += batch_device_count
        devices_failed += batch_failed_count

        with SessionLocal() as db:
            _aggregate_and_persist(
                run_repo=RunRepository(db),
                run_id=parent_run_id,
                signal=signal,
                canvas_nodes=canvas_nodes,
                canvas_edges=canvas_edges,
                child_results=all_results,
                final=False,
            )

    return all_results


async def _dispatch_children(
    signal: Any,
    parent_run_id: int,
    *,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
) -> list[dict[str, Any] | BaseException]:
    """Split devices into groups and dispatch Hatchet child workflows.

    When the inventory step's fan-out config has ``approval.enabled``, groups
    are dispatched in sequential batches of ``approval.batch_size`` groups,
    durably pausing the run between batches until a
    ``POST /runs/{id}/approve-batch`` (or ``approve-all``) call pushes the
    batch's event — this is the Wait & Run gate. See doc/WAIT-AND-RUN.md.

    No StepRunner/DeviceSessionPool is held across this function: the
    orchestrator itself never opens device sessions during dispatch, so there
    is nothing to suspend before the approval-gate waits — children own their
    own pools (see doc/DURABLE_SSH_SESSION.md §3.5, §5.5 item 4).
    """
    plan = _parse_fan_out_dispatch(signal)

    if not plan.groups:
        return []

    logger.info(
        "Dispatching %d child workflow group(s) parent_run_id=%s max_concurrency=%s "
        "approval_enabled=%s",
        len(plan.groups),
        parent_run_id,
        plan.max_concurrency,
        plan.approval_enabled,
    )

    if not plan.approval_enabled:
        return await _run_groups(
            signal,
            parent_run_id=parent_run_id,
            all_devices=plan.all_devices,
            max_concurrency=plan.max_concurrency,
            group_list=plan.groups,
            index_offset=0,
        )

    return await _dispatch_with_approval(
        signal,
        parent_run_id=parent_run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
        plan=plan,
    )


def _aggregate_and_persist(
    *,
    run_repo: Any,
    run_id: int,
    signal: Any,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    child_results: list[dict[str, Any] | BaseException],
    final: bool = True,
) -> tuple[bool, dict[str, dict[str, WorkflowContext]]]:
    """Merge child outcomes and update the parent run's WorkflowStepResult records.

    Returns ``(no_child_failure, merged_outcomes)`` where ``merged_outcomes`` maps
    each child-branch node_id → outcome_name → merged WorkflowContext (device union
    across children). The orchestrator feeds that map into ``resume_after_join`` so
    the fan-in node's inputs resolve from the fanned-in device union.

    ``final=False`` is used by Wait & Run to make finished batches inspectable
    while later batches are still gated on approval: nodes with no outcomes yet
    are left ``pending`` (they simply haven't run yet) instead of being marked
    ``skipped``, since more child_results may still arrive in a later call.
    """
    from models.workflow_context import WorkflowContext
    from services.execution.graph import child_node_ids
    from services.workflow_context.merge import merge_fan_out_contexts
    from services.workflow_context.secret_fields import redact_secrets_in_data

    # Children only produce the child branch (nodes before the fan-in node). The
    # post-join nodes are run once by the parent in resume_after_join, so they must
    # NOT be marked skipped here.
    child_ids = child_node_ids(
        signal.inventory_node_id, signal.join_node_id, canvas_nodes, canvas_edges
    )

    # Build a lookup from node_id → step result
    all_step_results = run_repo.get_step_results_for_run(run_id)
    step_result_by_node: dict[str, Any] = {sr.step_node_id: sr for sr in all_step_results}

    # Accumulate outcomes per child-branch node across all children
    per_node: dict[str, dict[str, list[WorkflowContext]]] = {nid: {} for nid in child_ids}
    # node_id -> {message, category, error_id} for the first child that reported a
    # step-level exception for that node (see StepRunner.execute_subgraph).
    node_errors: dict[str, dict[str, str]] = {}
    has_any_failure = False

    for child_result in child_results:
        if isinstance(child_result, BaseException):
            logger.error("Child workflow failed: %s", child_result)
            has_any_failure = True
            continue

        # child_result shape: {"execute_device_group": {node_id: {outcome_name: ctx_dict}}}
        task_output = child_result.get("execute_device_group", child_result)

        for node_id, err in (task_output.get("__step_errors__") or {}).items():
            node_errors.setdefault(node_id, err)

        for node_id, outcomes in task_output.items():
            if node_id == "__step_errors__" or node_id not in per_node:
                continue
            for outcome_name, ctx_dict in outcomes.items():
                ctx = WorkflowContext.model_validate(ctx_dict)
                per_node[node_id].setdefault(outcome_name, []).append(ctx)

    now = datetime.now(UTC)
    merged_outcomes: dict[str, dict[str, WorkflowContext]] = {}
    any_node_failed = False

    for node_id in child_ids:
        node_outcomes = per_node[node_id]
        step_result = step_result_by_node.get(node_id)

        if not node_outcomes:
            if final and step_result is not None:
                run_repo.update_step_result(
                    step_result,
                    status="skipped",
                    finished_at=now,
                )
            continue

        merged_output: dict[str, Any] = {}
        node_merged: dict[str, WorkflowContext] = {}
        for outcome_name, ctx_list in node_outcomes.items():
            merged_ctx = merge_fan_out_contexts(ctx_list) if len(ctx_list) > 1 else ctx_list[0]
            node_merged[outcome_name] = merged_ctx
            merged_output[outcome_name] = redact_secrets_in_data(merged_ctx.model_dump(mode="json"))
        merged_outcomes[node_id] = node_merged

        if step_result is not None:
            if has_any_failure or "failure" in node_outcomes:
                status = "partial" if "success" in node_outcomes else "failed"
            else:
                status = "success"
            if status == "failed":
                any_node_failed = True
            err = node_errors.get(node_id)
            run_repo.update_step_result(
                step_result,
                status=status,
                output={"outcomes": merged_output},
                error_message=err["message"] if err else None,
                error_category=err["category"] if err else None,
                error_id=err["error_id"] if err else None,
                started_at=now,
                finished_at=now,
            )

    return not (has_any_failure or any_node_failed), merged_outcomes
