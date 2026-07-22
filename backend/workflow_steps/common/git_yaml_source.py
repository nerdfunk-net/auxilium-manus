"""Read an arbitrary YAML file from a configured git source.

Unlike ``services.sources.git.git_source_service.GitDeviceService`` (which hard-codes
a ``devices:`` *list* schema for building ``DeviceContext`` objects), this helper is
schema-agnostic: it returns whatever the matched file parses to, for callers that
need a different YAML shape (e.g. a flat mapping of default attribute values).
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import yaml

from core.database import get_db_session
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key
from services.sources.git.git_source_service import clone_or_pull


def _find_first_file(repo_dir: Path, repository_path: str, pattern: str) -> Path | None:
    clean_path = repository_path.lstrip("/\\")
    search_root = repo_dir / clean_path if clean_path else repo_dir
    matches = glob.glob(str(search_root / "**" / pattern), recursive=True)
    if not matches:
        matches = glob.glob(str(search_root / pattern), recursive=False)
    if not matches:
        return None
    return Path(sorted(matches)[0])


def load_yaml_from_git_source(
    *, git_source_id: str, filename_pattern: str, step_id: str
) -> Any:
    """Clone/pull the configured git source and parse the first matching file.

    Raises ``ValueError`` for any configuration or content problem (missing source,
    no matching file, invalid YAML) — callers that need a "found nothing" fallback
    instead of a hard failure should catch and handle that themselves.
    """
    git_source_id = git_source_id.strip()
    filename_pattern = filename_pattern.strip()
    if not git_source_id:
        raise ValueError(f"{step_id}: git_source_id is not configured")
    if not filename_pattern:
        raise ValueError(f"{step_id}: filename_pattern is not configured")

    setting_key = build_source_key("git", git_source_id)
    db = get_db_session()
    try:
        setting = SettingsRepository(db).get_by_key(setting_key)
    finally:
        db.close()

    if setting is None:
        raise ValueError(f"{step_id}: git source '{git_source_id}' not found in settings")

    source_config: dict[str, Any] = {
        **(setting.value or {}),
        "source_id": git_source_id,
    }
    repo_dir = clone_or_pull(source_config)

    repository_path = str(source_config.get("repository_path") or "").strip()
    file_path = _find_first_file(repo_dir, repository_path, filename_pattern)
    if file_path is None:
        raise ValueError(
            f"{step_id}: no file matching '{filename_pattern}' found in git source "
            f"'{git_source_id}'"
        )

    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"{step_id}: invalid YAML in '{file_path.name}': {exc}") from exc

    return data
