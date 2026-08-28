"""Executor for the get-git-devices step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.git.device_service import GitDeviceService
from workflow_steps.common.device_builders import device_context_from_git_detail
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.git_repository_loader import load_git_repository

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

    raw_repository_id = config.get("git_repository_id")
    filename_pattern = (config.get("filename_pattern") or "").strip()
    directory = (config.get("directory") or "").strip()

    if raw_repository_id in (None, ""):
        raise ValueError("get-git-devices: git_repository_id is not configured")
    if not filename_pattern:
        raise ValueError("get-git-devices: filename_pattern is not configured")
    git_repository_id = int(raw_repository_id)

    logger.info(
        "get-git-devices started run_id=%s git_repository_id=%s filename_pattern=%s",
        run.id,
        git_repository_id,
        filename_pattern,
    )

    loop = asyncio.get_running_loop()
    repository = await loop.run_in_executor(None, lambda: load_git_repository(git_repository_id))

    service = GitDeviceService()
    devices, files_read = await loop.run_in_executor(
        None, lambda: service.fetch_devices(repository, filename_pattern, directory)
    )

    logger.info(
        "get-git-devices returning %d devices from %d file(s) run_id=%s",
        len(devices),
        files_read,
        run.id,
    )

    new_devices: dict[str, DeviceContext] = {}
    for index, detail in enumerate(devices):
        device_ctx = device_context_from_git_detail(
            detail,
            source_id=str(git_repository_id),
            index=index,
        )
        new_devices[device_ctx.id] = device_ctx

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.git_repository_id": git_repository_id,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.files_read": files_read,
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )
    return [StepOutcome(name="success", context=new_context)]
