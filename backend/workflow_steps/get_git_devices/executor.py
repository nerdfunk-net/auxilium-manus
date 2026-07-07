"""Executor for the get-git-devices step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.settings.source_keys import build_source_key
from services.sources.git.git_source_service import GitDeviceService
from workflow_steps.common.device_builders import device_context_from_git_detail

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    git_source_id = (config.get("git_source_id") or "").strip()
    filename_pattern = (config.get("filename_pattern") or "").strip()

    if not git_source_id:
        raise ValueError("get-git-devices: git_source_id is not configured")
    if not filename_pattern:
        raise ValueError("get-git-devices: filename_pattern is not configured")

    logger.info(
        "get-git-devices started run_id=%s git_source_id=%s filename_pattern=%s",
        run.id,
        git_source_id,
        filename_pattern,
    )

    setting_key = build_source_key("git", git_source_id)
    db = get_db_session()
    try:
        setting = SettingsRepository(db).get_by_key(setting_key)
    finally:
        db.close()

    if setting is None:
        raise ValueError(f"get-git-devices: git source '{git_source_id}' not found in settings")

    source_config: dict[str, Any] = {
        **(setting.value or {}),
        "source_id": git_source_id,
    }

    service = GitDeviceService()
    devices, files_read = await asyncio.get_event_loop().run_in_executor(
        None, lambda: service.fetch_devices(source_config, filename_pattern)
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
            source_id=git_source_id,
            index=index,
        )
        new_devices[device_ctx.id] = device_ctx

    fan_out_cfg: dict = config.get("fan_out") or {}
    fan_out_enabled = bool(fan_out_cfg.get("enabled", False))

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.source_id": git_source_id,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.files_read": files_read,
    }
    if fan_out_enabled:
        metadata_update["_fan_out"] = {
            "enabled": True,
            "mode": fan_out_cfg.get("mode", "per_device"),
            "chunk_size": max(1, int(fan_out_cfg.get("chunk_size", 1))),
            "max_concurrency": max(0, int(fan_out_cfg.get("max_concurrency", 0))),
            "inventory_node_id": node_id,
        }

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )
    return [StepOutcome(name="success", context=new_context)]
