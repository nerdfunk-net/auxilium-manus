"""Helpers for git-push commit staging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from models.workflow_context import WorkflowContext


def collect_export_paths_for_commit(
    context: WorkflowContext,
    *,
    repo_root: Path,
) -> list[str]:
    """Return repo-relative paths from upstream store-artifact metadata."""
    resolved_root = repo_root.resolve()
    paths: list[str] = []

    for key, value in context.metadata.items():
        if not str(key).endswith(".stored_artifacts") or not isinstance(value, list):
            continue
        for record in value:
            if not isinstance(record, dict):
                continue
            raw_path = record.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            try:
                relative = Path(raw_path).resolve().relative_to(resolved_root)
            except ValueError:
                continue
            paths.append(relative.as_posix())

    # Preserve order while dropping duplicates.
    seen: set[str] = set()
    unique_paths: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return unique_paths


def parse_commit_before_push(config: dict[str, Any]) -> bool:
    value = config.get("commit_before_push", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
