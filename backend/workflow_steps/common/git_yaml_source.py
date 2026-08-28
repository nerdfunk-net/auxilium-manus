"""Read an arbitrary YAML file from a configured git repository.

Unlike ``services.git.device_service.GitDeviceService`` (which hard-codes a
``devices:`` *list* schema for building ``DeviceContext`` objects), this helper is
schema-agnostic: it returns whatever the matched file parses to, for callers that
need a different YAML shape (e.g. a flat mapping of default attribute values).
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import yaml

from services.git.sync import clone_or_pull
from workflow_steps.common.git_repository_loader import load_git_repository


def _find_first_file(repo_dir: Path, directory: str, pattern: str) -> Path | None:
    clean_path = directory.lstrip("/\\")
    search_root = repo_dir / clean_path if clean_path else repo_dir
    matches = glob.glob(str(search_root / "**" / pattern), recursive=True)
    if not matches:
        matches = glob.glob(str(search_root / pattern), recursive=False)
    if not matches:
        return None
    return Path(sorted(matches)[0])


def load_yaml_from_git_source(
    *, git_repository_id: int | None, filename_pattern: str, step_id: str, directory: str = ""
) -> Any:
    """Clone/pull the configured git repository and parse the first matching file.

    Raises ``ValueError`` for any configuration or content problem (missing
    repository, no matching file, invalid YAML) — callers that need a "found
    nothing" fallback instead of a hard failure should catch and handle that
    themselves.
    """
    filename_pattern = filename_pattern.strip()
    if git_repository_id is None:
        raise ValueError(f"{step_id}: git_repository_id is not configured")
    if not filename_pattern:
        raise ValueError(f"{step_id}: filename_pattern is not configured")

    repository = load_git_repository(git_repository_id)
    repo_dir = clone_or_pull(repository)

    file_path = _find_first_file(repo_dir, directory.strip(), filename_pattern)
    if file_path is None:
        raise ValueError(
            f"{step_id}: no file matching '{filename_pattern}' found in git repository "
            f"'{repository['name']}'"
        )

    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"{step_id}: invalid YAML in '{file_path.name}': {exc}") from exc

    return data
