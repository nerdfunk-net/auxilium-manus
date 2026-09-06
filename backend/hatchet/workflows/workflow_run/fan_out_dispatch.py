"""Phase 2 of the fan-out parent: turn a FanOutSignal into device groups and
dispatch Hatchet child workflows (``DeviceGroupExecution``), optionally in
approval-gated batches (Wait & Run — see doc/WAIT-AND-RUN.md).

``_dispatch_with_approval`` and ``_dispatch_children`` live here together (not
in batch_approval.py) so the import graph stays one-directional:
fan_out_dispatch -> {batch_approval, aggregation}; batch_approval stays a leaf.
The lazy ``from core.database import SessionLocal`` inside
``_dispatch_with_approval`` is deliberate and must stay in-function.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from hatchet_sdk import DurableContext

from hatchet.workflows.device_group_execution import DeviceGroupInput, child_workflow
from hatchet.workflows.workflow_run.aggregation import _aggregate_and_persist
from hatchet.workflows.workflow_run.batch_approval import (
    _batch_needs_approval_gate,
    _device_names_for_groups,
    _wait_and_resume_batch_approval,
)

logger = logging.getLogger(__name__)


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

    assert isinstance(signal, FanOutSignal)  # noqa: S101  # type narrowing

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
