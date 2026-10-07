"""Fetch device data (YAML inventory files) from a git repository."""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.git.device_mapping import (
    MappingRule,
    apply_device_mapping,
    collect_available_keys,
    validate_device_mapping,
)
from services.git.sync import clone_or_pull

logger = logging.getLogger(__name__)


def _find_files(repo_dir: Path, directory: str, pattern: str) -> list[Path]:
    """Return all files in the repo that match *pattern* (glob syntax)."""
    # Strip leading slashes — pathlib treats "/" as absolute, which would escape the repo root.
    clean_path = directory.lstrip("/\\")
    search_root = repo_dir / clean_path if clean_path else repo_dir
    matches = glob.glob(str(search_root / "**" / pattern), recursive=True)
    if not matches:
        matches = glob.glob(str(search_root / pattern), recursive=False)
    return [Path(m) for m in sorted(matches)]


def _read_yaml_entries(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Read a YAML file; return its raw device entries and a problem description (or None).

    Accepted shapes: a root list of device dicts, or a root mapping whose ``devices`` key
    holds a list (or a single dict).
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning("Cannot parse YAML file %s: %s", path, exc)
        return [], f"{path.name}: not valid YAML ({type(exc).__name__})"

    raw_devices: Any = data
    if isinstance(data, dict):
        raw_devices = data.get("devices")
        if isinstance(raw_devices, dict):
            raw_devices = [raw_devices]
    if not isinstance(raw_devices, list):
        return [], (
            f"{path.name}: expected a list of devices (at the top level or under a 'devices' key)"
        )

    entries = [entry for entry in raw_devices if isinstance(entry, dict)]
    skipped = len(raw_devices) - len(entries)
    if skipped:
        return entries, f"{path.name}: {skipped} entr{'y' if skipped == 1 else 'ies'} not a mapping"
    return entries, None


def _parse_yaml_file(path: Path) -> list[dict[str, Any]]:
    """Read a YAML file and return its raw device entries (dicts only)."""
    return _read_yaml_entries(path)[0]


@dataclass(frozen=True)
class GitDeviceRecord:
    """One device: the raw file entry and its Nautobot-shaped mapped form."""

    raw: dict[str, Any]
    mapped: dict[str, Any]


@dataclass(frozen=True)
class GitDeviceFetchResult:
    records: list[GitDeviceRecord]
    files_read: int
    available_keys: list[str]
    # Human-readable problems (unparseable files, wrong shape, unmapped entries).
    warnings: list[str]


class GitDeviceService:
    """Fetches device data from a git repository.

    Call directly from async handlers — GitPython manages its own subprocess
    lifecycle and does not need an executor wrapper.
    """

    def fetch_devices(
        self,
        repository: dict[str, Any],
        filename_pattern: str,
        directory: str = "",
        device_mapping: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return ``(mapped devices, files_read)``; see :meth:`fetch_records`."""
        result = self.fetch_records(repository, filename_pattern, directory, device_mapping)
        return [record.mapped for record in result.records], result.files_read

    def fetch_records(
        self,
        repository: dict[str, Any],
        filename_pattern: str,
        directory: str = "",
        device_mapping: list[dict[str, Any]] | None = None,
    ) -> GitDeviceFetchResult:
        """Clone/pull the repo, find matching files, and map device entries.

        Args:
            repository: A ``GitRepository``-shaped dict (see
                ``GitRepositoryService._to_dict``).
            filename_pattern: Glob pattern for files to search (e.g. ``*.yaml``).
            directory: Subdirectory within the repository to search.
            device_mapping: ``[{source, target}]`` rows (see
                ``services.git.device_mapping``); empty/None uses the default mapping.

        Raises ``ValueError`` for an invalid mapping (before any git work).
        """
        rules: list[MappingRule] = validate_device_mapping(device_mapping)
        name = repository.get("name") or repository.get("id")
        logger.info("fetch_devices START — repo=%s pattern=%s", name, filename_pattern)

        repo_dir = clone_or_pull(repository)

        if directory.startswith(("/", "\\")):
            logger.warning(
                "Git repository '%s': directory %r starts with a slash — "
                "it will be treated as relative to the repo root",
                name,
                directory,
            )

        files = _find_files(repo_dir, directory, filename_pattern)
        logger.info(
            "Git repository '%s': found %d file(s) matching '%s'",
            name,
            len(files),
            filename_pattern,
        )

        warnings: list[str] = []
        if not files:
            warnings.append(f"No file matching '{filename_pattern}' found")

        raw_entries: list[dict[str, Any]] = []
        for file_path in files:
            entries, problem = _read_yaml_entries(file_path)
            raw_entries.extend(entries)
            if problem:
                warnings.append(problem)

        records: list[GitDeviceRecord] = []
        for entry in raw_entries:
            mapped = apply_device_mapping(entry, rules)
            if mapped is not None:
                records.append(GitDeviceRecord(raw=entry, mapped=mapped))
        unmapped = len(raw_entries) - len(records)
        if unmapped:
            name_source = next((r.source for r in rules if r.target == "name"), "name")
            warnings.append(
                f"{unmapped} entr{'y' if unmapped == 1 else 'ies'} skipped: "
                f"no value for the key mapped to Device name ('{name_source}')"
            )
        for warning in warnings:
            logger.warning("Git repository '%s': %s", name, warning)

        logger.info(
            "fetch_devices DONE — repo=%s devices=%d files=%d", name, len(records), len(files)
        )
        return GitDeviceFetchResult(
            records=records,
            files_read=len(files),
            available_keys=collect_available_keys(raw_entries),
            warnings=warnings,
        )
