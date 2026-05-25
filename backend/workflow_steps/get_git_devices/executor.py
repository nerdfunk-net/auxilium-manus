"""Executor for the get-git-devices step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key
from services.sources.git.git_source_service import GitDeviceService

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    git_source_id = (config.get("git_source_id") or "").strip()
    filename_pattern = (config.get("filename_pattern") or "").strip()

    if not git_source_id:
        raise ValueError("get-git-devices: git_source_id is not configured")
    if not filename_pattern:
        raise ValueError("get-git-devices: filename_pattern is not configured")

    setting_key = build_source_key("git", git_source_id)
    db = get_db_session()
    try:
        setting = SettingsRepository(db).get_by_key(setting_key)
    finally:
        db.close()

    if setting is None:
        raise ValueError(
            f"get-git-devices: git source '{git_source_id}' not found in settings"
        )

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

    return {
        "general": {
            "source_id": git_source_id,
            "total": len(devices),
            "files_read": files_read,
        },
        "device_ids": [None] * len(devices),
        "device_details": devices,
    }
