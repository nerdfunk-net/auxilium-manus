"""Executor for the get-from-list step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_list import device_context_from_entry, normalize_device_entries
from workflow_steps.common.fan_out import build_fan_out_metadata

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    logger.info("get-from-list started run_id=%s", run.id)

    device_entries = normalize_device_entries(config.get("devices"))
    if not device_entries:
        raise ValueError("get-from-list: at least one device name or IP address is required")

    new_devices = {
        device.id: device
        for index, entry in enumerate(device_entries)
        for device in [device_context_from_entry(entry, index=index, node_id=node_id)]
    }

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.devices": [device.name for device in new_devices.values()],
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

    logger.info(
        "get-from-list returning %d devices run_id=%s",
        len(new_devices),
        run.id,
    )

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )
    return [StepOutcome(name="success", context=new_context)]
