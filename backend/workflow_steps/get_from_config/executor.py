"""Executor for the get-from-config step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.git.content_search_service import GitContentSearchService
from services.git.sync import clone_or_pull
from services.network.cisco_config_parsing import parse_cisco_config_text
from workflow_steps.common.device_builders import device_context_from_config_match
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.git_repository_loader import load_git_repository

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedGetFromConfig:
    git_repository_id: int
    search_text: str
    directory: str
    file_filter: str
    recursive: bool
    include_history: bool
    case_sensitive: bool


def _parse_get_from_config(config: dict[str, Any]) -> _ParsedGetFromConfig:
    raw_repository_id = config.get("git_repository_id")
    search_text = (config.get("search_text") or "").strip()
    if raw_repository_id in (None, ""):
        raise ValueError("get-from-config: git_repository_id is not configured")
    if not search_text:
        raise ValueError("get-from-config: search_text is not configured")
    return _ParsedGetFromConfig(
        git_repository_id=int(raw_repository_id),
        search_text=search_text,
        directory=(config.get("directory") or "").strip(),
        file_filter=(config.get("file_filter") or "").strip(),
        recursive=bool(config.get("recursive", True)),
        include_history=bool(config.get("include_history", False)),
        case_sensitive=bool(config.get("case_sensitive", False)),
    )


async def _load_git_repo_for_search(
    git_repository_id: int,
    loop: asyncio.AbstractEventLoop,
) -> tuple[Any, Any]:
    repository = await loop.run_in_executor(None, lambda: load_git_repository(git_repository_id))
    repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(repository))
    return repository, repo_dir


def _devices_from_config_matches(
    matches: list[Any],
    *,
    git_repository_id: int,
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
            source_id=str(git_repository_id),
            file_path=match.file_path,
            commit=match.commit,
        )

    return {device.id: device for device in new_devices.values()}


def _build_get_from_config_outcome(
    *,
    context: WorkflowContext,
    node_id: str,
    config: dict[str, Any],
    git_repository_id: int,
    devices_by_id: dict[str, DeviceContext],
    matches_found: int,
    files_scanned: int,
) -> list[StepOutcome]:
    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict[str, Any] = {
        **context.metadata,
        f"{node_id}.git_repository_id": git_repository_id,
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
        "get-from-config started run_id=%s git_repository_id=%s search_text_len=%d",
        run.id,
        parsed.git_repository_id,
        len(parsed.search_text),
    )

    loop = asyncio.get_running_loop()
    _repository, repo_dir = await _load_git_repo_for_search(parsed.git_repository_id, loop)
    matches, files_scanned = await loop.run_in_executor(
        None,
        lambda: GitContentSearchService().search(
            repo_dir,
            directory=parsed.directory,
            file_filter=parsed.file_filter,
            recursive=parsed.recursive,
            include_history=parsed.include_history,
            search_text=parsed.search_text,
            case_sensitive=parsed.case_sensitive,
        ),
    )
    devices_by_id = _devices_from_config_matches(
        matches, git_repository_id=parsed.git_repository_id, run_id=run.id
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
        git_repository_id=parsed.git_repository_id,
        devices_by_id=devices_by_id,
        matches_found=len(matches),
        files_scanned=files_scanned,
    )
