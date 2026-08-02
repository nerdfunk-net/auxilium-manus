"""Executor for the get-from-config step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.settings.settings_service import SettingsService
from services.sources.git.git_content_search_service import GitContentSearchService
from services.sources.git.git_source_service import clone_or_pull
from workflow_steps.common.cisco_config_parsing import parse_cisco_config_text
from workflow_steps.common.device_builders import device_context_from_config_match
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

    git_source_id = (config.get("git_source_id") or "").strip()
    search_text = (config.get("search_text") or "").strip()
    directory = (config.get("directory") or "").strip()
    file_filter = (config.get("file_filter") or "").strip()
    recursive = bool(config.get("recursive", True))
    include_history = bool(config.get("include_history", False))
    case_sensitive = bool(config.get("case_sensitive", False))

    if not git_source_id:
        raise ValueError("get-from-config: git_source_id is not configured")
    if not search_text:
        raise ValueError("get-from-config: search_text is not configured")

    logger.info(
        "get-from-config started run_id=%s git_source_id=%s search_text_len=%d",
        run.id,
        git_source_id,
        len(search_text),
    )

    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config("git", git_source_id)
        except HTTPException as exc:
            raise ValueError(f"get-from-config: {exc.detail}") from exc
    finally:
        db.close()

    loop = asyncio.get_event_loop()
    repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(source_config))

    search_service = GitContentSearchService()
    matches, files_scanned = await loop.run_in_executor(
        None,
        lambda: search_service.search(
            repo_dir,
            source_config,
            directory=directory,
            file_filter=file_filter,
            recursive=recursive,
            include_history=include_history,
            search_text=search_text,
            case_sensitive=case_sensitive,
        ),
    )

    new_devices: dict[str, DeviceContext] = {}
    for match in matches:
        try:
            parsed = parse_cisco_config_text(match.content, None)
        except ValueError:
            logger.warning(
                "get-from-config: could not parse %s (unrecognized platform) run_id=%s",
                match.file_path,
                run.id,
            )
            continue

        hostname = str(parsed.get("hostname") or "").strip()
        if not hostname:
            logger.warning(
                "get-from-config: no hostname found in %s run_id=%s",
                match.file_path,
                run.id,
            )
            continue

        key = hostname.lower()
        if key in new_devices:
            continue

        new_devices[key] = device_context_from_config_match(
            hostname,
            source_id=git_source_id,
            file_path=match.file_path,
            commit=match.commit,
        )

    devices_by_id = {device.id: device for device in new_devices.values()}

    logger.info(
        "get-from-config finished devices=%d matches=%d files_scanned=%d run_id=%s",
        len(devices_by_id),
        len(matches),
        files_scanned,
        run.id,
    )

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict[str, Any] = {
        **context.metadata,
        f"{node_id}.source_id": git_source_id,
        f"{node_id}.total": len(devices_by_id),
        f"{node_id}.files_scanned": files_scanned,
        f"{node_id}.matches_found": len(matches),
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **devices_by_id},
            "metadata": metadata_update,
        }
    )
    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=(f"Found {len(devices_by_id)} device(s) from {len(matches)} matching file(s)"),
        )
    ]
