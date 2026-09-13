"""Collect device config files for batfish-init-snapshot's git config_source.

Files are collected by glob match, not by per-device path mapping -- Batfish
derives each node's identity from the config text's own hostname line, not
its filename or path (see doc/BATFISH_INTEGRATION.md "Building the snapshot
directory"). The caller-supplied glob_pattern decides whether devices are
told apart by filename suffix (e.g. "**/*.running.cfg") or by directory
(e.g. "configs/running/**/*.cfg") -- pathlib.Path.glob understands "**" as a
recursive segment natively, so neither convention needs special-casing here.

Safety posture mirrors services/git/content_search_service.py's
GitContentSearchService (a file-count cap, a per-file size cap, .git
exclusion) but with materially higher limits: that module was tuned for an
interactive search-preview feature, not a full-fleet snapshot's
completeness. The escape guard mirrors
read_config/executor.py::_resolve_target_path's resolve()+relative_to()
containment check, applied to both base_path and every matched file (to
also reject symlinks that resolve outside the repository).
"""

from __future__ import annotations

import shutil
from pathlib import Path

MAX_GIT_SOURCE_FILES = 20_000
MAX_GIT_SOURCE_FILE_SIZE = 10 * 1024 * 1024

_STEP_ID = "batfish-init-snapshot"


def _resolve_base_dir(repo_root: Path, base_path: str) -> Path:
    root = repo_root.resolve()
    sub = base_path.strip("/\\")
    target = (root / sub).resolve() if sub else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: base_path {base_path!r} escapes the repository") from exc
    if not target.is_dir():
        raise ValueError(f"{_STEP_ID}: base_path {base_path!r} does not exist in the repository")
    return target


def collect_git_source_files(
    *, repo_root: Path, base_path: str, glob_pattern: str
) -> list[Path]:
    """Return every file under base_path matching glob_pattern.

    Raises ValueError on an empty match set or past MAX_GIT_SOURCE_FILES --
    a silently truncated or empty production snapshot is a worse failure
    mode than a loud one.
    """
    pattern = glob_pattern.strip()
    if not pattern:
        raise ValueError(f"{_STEP_ID}: glob_pattern is required when config_source is 'git'")

    repo_root = repo_root.resolve()
    base_dir = _resolve_base_dir(repo_root, base_path)

    matches: list[Path] = []
    for candidate in sorted(base_dir.glob(pattern)):
        if not candidate.is_file():
            continue
        try:
            rel = candidate.relative_to(repo_root)
        except ValueError:
            continue
        if ".git" in rel.parts:
            continue
        try:
            resolved = candidate.resolve()
            resolved.relative_to(repo_root)  # reject symlinks escaping the repo
        except (OSError, ValueError):
            continue
        try:
            if resolved.stat().st_size > MAX_GIT_SOURCE_FILE_SIZE:
                continue
        except OSError:
            continue

        matches.append(resolved)
        if len(matches) > MAX_GIT_SOURCE_FILES:
            raise ValueError(
                f"{_STEP_ID}: glob_pattern matched more than {MAX_GIT_SOURCE_FILES} files "
                "-- narrow base_path/glob_pattern"
            )

    if not matches:
        raise ValueError(
            f"{_STEP_ID}: no files matched base_path={base_path!r} glob_pattern={glob_pattern!r}"
        )
    return matches


def copy_git_source_files_into(configs_dir: Path, files: list[Path]) -> None:
    """Copy every matched file into configs_dir with an index-prefixed name.

    Filenames are cosmetic to Batfish (identity comes from each file's own
    hostname line -- see module docstring), so an index prefix is enough to
    avoid same-basename collisions across different source subdirectories
    without needing to reconstruct the original relative directory structure.
    """
    for idx, path in enumerate(files):
        shutil.copy2(path, configs_dir / f"{idx:05d}-{path.name}")
