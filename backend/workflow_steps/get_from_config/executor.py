"""Executor for the get-from-config step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.network.cisco_config_parsing import parse_cisco_config_text
from services.settings.exceptions import SourceConfigError
from services.settings.settings_service import SettingsService
from services.sources.git.git_content_search_service import GitContentSearchService
from services.sources.git.git_source_service import clone_or_pull
from workflow_steps.common.device_builders import device_context_from_config_match
from workflow_steps.common.fan_out import build_fan_out_metadata

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedGetFromConfig:
    git_source_id: str
    search_text: str
    directory: str
    file_filter: str
    recursive: bool
    include_history: bool
    case_sensitive: bool


def _parse_get_from_config(config: dict[str, Any]) -> _ParsedGetFromConfig:
    git_source_id = (config.get("git_source_id") or "").strip()
    search_text = (config.get("search_text") or "").strip()
    if not git_source_id:
        raise ValueError("get-from-config: git_source_id is not configured")
    if not search_text:
        raise ValueError("get-from-config: search_text is not configured")
    return _ParsedGetFromConfig(
        git_source_id=git_source_id,
        search_text=search_text,
        directory=(config.get("directory") or "").strip(),
        file_filter=(config.get("file_filter") or "").strip(),
        recursive=bool(config.get("recursive", True)),
        include_history=bool(config.get("include_history", False)),
        case_sensitive=bool(config.get("case_sensitive", False)),
    )


async def _load_git_repo_for_search(
    git_source_id: str,
    loop: asyncio.AbstractEventLoop,
) -> tuple[Any, Any]:
    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config_for_step("git", git_source_id)
        except SourceConfigError as exc:
            raise ValueError(f"get-from-config: {exc}") from exc
    finally:
        db.close()

    repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(source_config))
    return source_config, repo_dir


def _devices_from_config_matches(
    matches: list[Any],
    *,
    git_source_id: str,
    run_id: Any,
) -> dict[str, DeviceContext]:
    new_devices: dict[str, DeviceContext] = {}
    for match in matches:
        try:
            parsed = parse_cisco_config_text(match.content, None)
        except ValueError:
            logger.warning(
                "get-from-config: could not parse %s (unrecognized platform) run_id=%s",
                match.file_path,
                run_id,
            )
            continue

        hostname = str(parsed.get("hostname") or "").strip()
        if not hostname:
            logger.warning(
                "get-from-config: no hostname found in %s run_id=%s",
                match.file_path,
                run_id,
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

    return {device.id: device for device in new_devices.values()}


def _build_get_from_config_outcome(
    *,
    context: WorkflowContext,
    node_id: str,
    config: dict[str, Any],
    git_source_id: str,
    devices_by_id: dict[str, DeviceContext],
    matches_found: int,
    files_scanned: int,
) -> list[StepOutcome]:
    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict[str, Any] = {
        **context.metadata,
        f"{node_id}.source_id": git_source_id,
        f"{node_id}.total": len(devices_by_id),
        f"{node_id}.files_scanned": files_scanned,
        f"{node_id}.matches_found": matches_found,
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
            summary=(f"Found {len(devices_by_id)} device(s) from {matches_found} matching file(s)"),
        )
    ]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service

    parsed = _parse_get_from_config(config)

    logger.info(
        "get-from-config started run_id=%s git_source_id=%s search_text_len=%d",
        run.id,
        parsed.git_source_id,
        len(parsed.search_text),
    )

    loop = asyncio.get_running_loop()
    source_config, repo_dir = await _load_git_repo_for_search(parsed.git_source_id, loop)
    matches, files_scanned = await loop.run_in_executor(
        None,
        lambda: GitContentSearchService().search(
            repo_dir,
            source_config,
            directory=parsed.directory,
            file_filter=parsed.file_filter,
            recursive=parsed.recursive,
            include_history=parsed.include_history,
            search_text=parsed.search_text,
            case_sensitive=parsed.case_sensitive,
        ),
    )
    devices_by_id = _devices_from_config_matches(
        matches, git_source_id=parsed.git_source_id, run_id=run.id
    )
    logger.info(
        "get-from-config finished devices=%d matches=%d files_scanned=%d run_id=%s",
        len(devices_by_id),
        len(matches),
        files_scanned,
        run.id,
    )
    return _build_get_from_config_outcome(
        context=context,
        node_id=node_id,
        config=config,
        git_source_id=parsed.git_source_id,
        devices_by_id=devices_by_id,
        matches_found=len(matches),
        files_scanned=files_scanned,
    )
