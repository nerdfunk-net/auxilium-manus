"""Read reference file content for compare-data from filesystem or git."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.config import settings
from services.git.paths import repo_path as get_repo_path
from services.git.paths import resolve_within_repo, validate_relative_glob
from services.git.tree_scope import git_work_tree
from services.workflow_context.device_template import sanitize_relative_path
from workflow_steps.common.git_repository_loader import load_git_repository

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

    subdir = (
        validate_relative_glob(
            reference_subdirectory.strip("/\\"), field="reference_subdirectory", allow_empty=True
        )
        or "references"
    )
    root = Path(settings.data_directory).resolve()
    target = (root / subdir / normalized).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Unsafe reference path: outside the data directory")
    return target


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
    return resolve_within_repo(get_repo_path(repository), str(normalized))


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
    raw_repository_id = config.get("git_repository_id")
    if raw_repository_id in (None, ""):
        raise ValueError("compare-data: git_repository_id is required when reference_location=git")

    repository = load_git_repository(int(raw_repository_id))
    repository_subdirectory = str(
        config.get("repository_subdirectory") or defaults.get("repository_subdirectory") or ""
    )
    target = _git_reference_path(
        repository=repository,
        repository_subdirectory=repository_subdirectory,
        relative_path=relative_path,
    )

    def _read_sync() -> str:
        # Under the repository lease. A pull is deduplicated per repository for a few seconds
        # (git_work_tree), so N devices cause one pull, not N (C4-04, C2-06).
        pull_before_read = config.get("pull_before_read", defaults.get("pull_before_read"))
        from workflow_steps.common.step_flags import parse_bool_flag

        with git_work_tree(
            repository,
            sync="strict" if parse_bool_flag({"v": pull_before_read}, "v") else "never",
        ):
            if not target.is_file():
                # relative path only: the absolute server path must not leak (C4-04)
                raise FileNotFoundError(f"Reference file not found: {relative_path}")
            content = target.read_text(encoding="utf-8")
        logger.info(
            "compare-data read git reference repo=%s path=%s bytes=%d",
            repository.get("name"),
            relative_path,
            len(content),
        )
        return content

    return await asyncio.to_thread(_read_sync)
