"""Executor for the split-virtual-chassis step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, DeviceStatus, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_outcomes import build_outcomes, mark_device_failed
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.split_virtual_chassis.members import (
    STEP_ID,
    SplitSettings,
    parse_settings,
    split_stack_device,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


def _split_all(
    context: WorkflowContext, settings: SplitSettings, node_id: str
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], int]:
    """Split every stack device; returns ``(members, failed, stack_count)``."""
    members: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    stacks = 0
    for key, device in context.devices.items():
        if device.status == DeviceStatus.FAILED:
            failed[key] = device
            continue
        split = split_stack_device(device, settings)
        if split is None:
            failed[key] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=STEP_ID,
                code="not_a_stack",
                message=(
                    f"Device {device.name!r} has no {settings.attribute_bag!r} stack data; "
                    "use a Get Virtual Chassis step with split_members off upstream"
                ),
            )
            continue
        clash = sorted(m.id for m in split if m.id in members)
        if clash:
            failed[key] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=STEP_ID,
                code="member_id_conflict",
                message=f"Stack member id(s) {', '.join(clash)} already belong to another stack",
            )
            continue
        stacks += 1
        members.update({m.id: m for m in split})
    return members, failed, stacks


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: no I/O in this step

    settings = parse_settings(config)
    logger.info(
        "split-virtual-chassis started run_id=%s node_id=%s devices=%d attribute_bag=%s",
        log_run_id(run),
        node_id,
        len(context.devices),
        settings.attribute_bag,
    )

    members, failed, stacks = _split_all(context, settings, node_id)

    logger.info(
        "split-virtual-chassis finished stacks=%d members=%d failed=%d run_id=%s",
        stacks,
        len(members),
        len(failed),
        log_run_id(run),
    )

    return build_outcomes(
        context,
        members,
        failed,
        metadata={f"{node_id}.stacks": stacks, f"{node_id}.members": len(members)},
        success_summary=f"split {stacks} stack(s) into {len(members)} member device(s)",
        failure_summary=f"{len(failed)} device(s) could not be split",
    )
