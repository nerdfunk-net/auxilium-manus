"""Wait & Run (batch approval) helpers: build the WorkflowRun.approval_state
shape, format the pause message, decide whether a batch needs an approval gate,
and durably pause/resume the run between batches. See doc/WAIT-AND-RUN.md.

Leaf module — imports no workflow_run sibling at runtime.
``_wait_and_resume_batch_approval`` keeps its injected-dependency signature
(``SessionLocal=…, RunRepository=…``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hatchet_sdk import DurableContext

from services.execution.run_events import STEP_EVENT_LOOKBACK, batch_approval_event_key

if TYPE_CHECKING:
    from hatchet.workflows.workflow_run.fan_out_dispatch import _FanOutDispatchPlan

logger = logging.getLogger(__name__)

# Cap on how many device names are stamped into WorkflowRun.approval_state —
# it's a UI display hint, not a source of truth (the real device set lives in
# the child WorkflowContext), so an unbounded list would just bloat the row.
MAX_APPROVAL_STATE_DEVICE_NAMES = 25


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
