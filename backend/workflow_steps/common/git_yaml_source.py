"""Read an arbitrary YAML file from a configured git repository.

Unlike ``services.git.device_service.GitDeviceService`` (which hard-codes a
``devices:`` *list* schema for building ``DeviceContext`` objects), this helper is
schema-agnostic: it returns whatever the matched file parses to, for callers that
need a different YAML shape (e.g. a flat mapping of default attribute values).
"""

from __future__ import annotations

from typing import Any

import yaml

from services.git.paths import list_repo_files
from services.git.sync import git_checkout
from workflow_steps.common.git_repository_loader import load_git_repository


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
    with git_checkout(repository) as repo_dir:
        matches = list_repo_files(repo_dir, directory.strip(), filename_pattern)
        file_path = matches[0] if matches else None
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
