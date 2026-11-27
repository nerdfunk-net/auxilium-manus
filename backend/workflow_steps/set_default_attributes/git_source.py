"""Read an arbitrary YAML file from a configured git repository.

Unlike ``services.git.device_service.GitDeviceService`` (which hard-codes a
``devices:`` *list* schema for building ``DeviceContext`` objects), this helper is
schema-agnostic: it returns whatever the matched file parses to, for callers that
need a different YAML shape (e.g. a flat mapping of default attribute values).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from services.git.paths import list_repo_files
from services.git.sync import git_checkout
from workflow_steps.common.git_repository_loader import load_git_repository

_NAMED_MATCHES_CAP = 5


def _several_matches_error(
    *,
    step_id: str,
    filename_pattern: str,
    repository_name: str,
    repo_dir: Path,
    matches: list[Path],
) -> ValueError:
    """Name the matching files relative to the repository (never the server path)."""
    root = Path(repo_dir).resolve()
    names = [match.relative_to(root).as_posix() for match in matches[:_NAMED_MATCHES_CAP]]
    if len(matches) > _NAMED_MATCHES_CAP:
        names.append("...")
    return ValueError(
        f"{step_id}: {len(matches)} files match '{filename_pattern}' in git repository "
        f"'{repository_name}' ({', '.join(names)}); narrow filename_pattern or directory "
        "so that exactly one file matches"
    )


def load_yaml_from_git_source(
    *, git_repository_id: int | None, filename_pattern: str, step_id: str, directory: str = ""
) -> Any:
    """Clone/pull the configured git repository and parse the one matching file.

    Raises ``ValueError`` for any configuration or content problem (missing
    repository, no matching file, several matching files, invalid YAML) — callers that need a "found
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
        if not matches:
            raise ValueError(
                f"{step_id}: no file matching '{filename_pattern}' found in git repository "
                f"'{repository['name']}'"
            )
        if len(matches) > 1:
            raise _several_matches_error(
                step_id=step_id,
                filename_pattern=filename_pattern,
                repository_name=repository["name"],
                repo_dir=repo_dir,
                matches=matches,
            )
        file_path = matches[0]

        try:
            with file_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(f"{step_id}: invalid YAML in '{file_path.name}': {exc}") from exc

    return data
