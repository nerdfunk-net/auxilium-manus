"""Read reference file content for compare-data from filesystem or git."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.config import settings
from services.git.paths import repo_path as get_repo_path
from workflow_steps.common.device_template import sanitize_relative_path
from workflow_steps.common.git_source_loader import load_git_source_repository

logger = logging.getLogger(__name__)

_REFERENCE_LOCATIONS = frozenset({"filesystem", "git"})


def parse_reference_location(config: dict[str, Any]) -> str:
    location = str(config.get("reference_location") or "filesystem").strip().lower()
    if location not in _REFERENCE_LOCATIONS:
        raise ValueError(
            f"compare-data: reference_location must be one of {sorted(_REFERENCE_LOCATIONS)}"
        )
    return location


def _filesystem_reference_path(*, reference_subdirectory: str, relative_path: str) -> Path:
    normalized = Path(relative_path.lstrip("/\\"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Unsafe reference path: {relative_path!r}")

    subdir = reference_subdirectory.strip("/\\") or "references"
    return settings.data_directory / subdir / normalized


def _git_reference_path(
    *,
    repository: dict[str, Any],
    repository_subdirectory: str,
    relative_path: str,
) -> Path:
    parts: list[str] = []
    if repository_subdirectory.strip("/\\"):
        parts.append(repository_subdirectory.strip("/\\"))
    parts.append(relative_path.lstrip("/\\"))
    combined = sanitize_relative_path("/".join(parts))
    normalized = Path(combined)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Unsafe reference path: {relative_path!r}")
    return get_repo_path(repository) / normalized


async def read_reference_text(
    *,
    config: dict[str, Any],
    relative_path: str,
) -> str:
    """Load reference file content from the configured location."""
    location = parse_reference_location(config)
    if location == "filesystem":
        return await asyncio.to_thread(
            _read_filesystem_sync,
            config,
            relative_path,
        )
    return await _read_git_async(config, relative_path)


def _read_filesystem_sync(config: dict[str, Any], relative_path: str) -> str:
    from workflow_steps.compare_data.config import get_config

    defaults = get_config()
    reference_subdirectory = str(
        config.get("reference_subdirectory")
        or defaults.get("reference_subdirectory")
        or "references"
    )
    target = _filesystem_reference_path(
        reference_subdirectory=reference_subdirectory,
        relative_path=relative_path,
    )
    if not target.is_file():
        raise FileNotFoundError(f"Reference file not found: {target}")
    content = target.read_text(encoding="utf-8")
    logger.info("compare-data read filesystem reference path=%s bytes=%d", target, len(content))
    return content


async def _read_git_async(config: dict[str, Any], relative_path: str) -> str:
    from workflow_steps.compare_data.config import get_config

    defaults = get_config()
    git_source_id = str(config.get("git_source_id") or "").strip().lower()
    if not git_source_id:
        raise ValueError("compare-data: git_source_id is required when reference_location=git")

    repository = load_git_source_repository(git_source_id)
    repository_subdirectory = str(
        config.get("repository_subdirectory")
        or defaults.get("repository_subdirectory")
        or ""
    )
    target = _git_reference_path(
        repository=repository,
        repository_subdirectory=repository_subdirectory,
        relative_path=relative_path,
    )

    def _read_sync() -> str:
        import service_factory

        git_service = service_factory.build_git_service()
        repo = git_service.open_or_clone(repository)
        pull_before_read = config.get("pull_before_read", defaults.get("pull_before_read"))
        if pull_before_read is True or (
            isinstance(pull_before_read, str)
            and pull_before_read.strip().lower() in {"1", "true", "yes", "on"}
        ):
            pull_result = git_service.pull(repository, repo=repo)
            if not pull_result.success:
                raise RuntimeError(pull_result.message)
        if not target.is_file():
            raise FileNotFoundError(f"Reference file not found: {target}")
        content = target.read_text(encoding="utf-8")
        logger.info(
            "compare-data read git reference repo=%s path=%s bytes=%d",
            repository.get("name"),
            target,
            len(content),
        )
        return content

    return await asyncio.to_thread(_read_sync)
