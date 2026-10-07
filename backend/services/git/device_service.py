"""Fetch device data (YAML or CSV inventory files) from a git repository."""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.git.csv_device_reader import ALLOWED_DELIMITERS, read_csv_rows
from services.git.device_grouping import map_single_row, merge_device_rows
from services.git.device_mapping import (
    NAME_TARGET,
    MappingRule,
    collect_available_keys,
    validate_device_mapping,
    with_implicit_custom_field_rules,
)
from services.git.sync import clone_or_pull

logger = logging.getLogger(__name__)

FILE_FORMATS: tuple[str, ...] = ("yaml", "csv")


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
        **file_options: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return ``(mapped devices, files_read)``; see :meth:`fetch_records`."""
        result = self.fetch_records(
            repository, filename_pattern, directory, device_mapping, **file_options
        )
        return [record.mapped for record in result.records], result.files_read

    def fetch_records(
        self,
        repository: dict[str, Any],
        filename_pattern: str,
        directory: str = "",
        device_mapping: list[dict[str, Any]] | None = None,
        *,
        file_format: str = "yaml",
        csv_delimiter: str = ";",
        csv_multiline: bool = False,
    ) -> GitDeviceFetchResult:
        """Clone/pull the repo, find matching files, and map device entries.

        Args:
            repository: A ``GitRepository``-shaped dict (see
                ``GitRepositoryService._to_dict``).
            filename_pattern: Glob pattern for files to search (e.g. ``*.yaml``).
            directory: Subdirectory within the repository to search.
            device_mapping: ``[{source, target}]`` rows (see
                ``services.git.device_mapping``); empty/None uses the default mapping.
            file_format: ``"yaml"`` or ``"csv"``.
            csv_delimiter: Column delimiter of CSV files.
            csv_multiline: CSV only — merge all lines with the same device name.

        Raises ``ValueError`` for invalid options or mapping (before any git work).
        """
        if file_format not in FILE_FORMATS:
            raise ValueError(f"file_format must be one of {', '.join(FILE_FORMATS)}")
        if file_format == "csv" and csv_delimiter not in ALLOWED_DELIMITERS:
            raise ValueError("csv_delimiter must be one of ; , tab |")
        base_rules = validate_device_mapping(device_mapping)
        name = repository.get("name") or repository.get("id")
        logger.info(
            "fetch_devices START — repo=%s pattern=%s format=%s",
            name,
            filename_pattern,
            file_format,
        )

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
            if file_format == "csv":
                entries, problems = read_csv_rows(file_path, csv_delimiter)
                warnings.extend(problems)
            else:
                entries, problem = _read_yaml_entries(file_path)
                warnings.extend([problem] if problem else [])
            raw_entries.extend(entries)

        top_level_keys = list(dict.fromkeys(key for entry in raw_entries for key in entry))
        rules = with_implicit_custom_field_rules(base_rules, top_level_keys)

        if file_format == "csv" and csv_multiline:
            groups, group_warnings = merge_device_rows(raw_entries, rules)
            records = [GitDeviceRecord(raw=g.raw, mapped=g.mapped) for g in groups]
            warnings.extend(group_warnings)
        else:
            records = []
            for entry in raw_entries:
                mapped = map_single_row(entry, rules)
                if mapped is not None:
                    records.append(GitDeviceRecord(raw=entry, mapped=mapped))
            warnings.extend(_single_mode_warnings(records, len(raw_entries), rules, file_format))

        for warning in warnings:
            logger.warning("Git repository '%s': %s", name, warning)
        logger.info(
            "fetch_devices DONE — repo=%s devices=%d files=%d", name, len(records), len(files)
        )
        return GitDeviceFetchResult(
            records=records,
            files_read=len(files),
            available_keys=(
                sorted(top_level_keys)
                if file_format == "csv"
                else collect_available_keys(raw_entries)
            ),
            warnings=warnings,
        )


def _single_mode_warnings(
    records: list[GitDeviceRecord],
    entry_count: int,
    rules: list[MappingRule],
    file_format: str,
) -> list[str]:
    """Warnings for one-entry-per-device reading: skipped entries and repeated names."""
    warnings: list[str] = []
    unmapped = entry_count - len(records)
    if unmapped:
        name_source = next((r.source for r in rules if r.target == NAME_TARGET), NAME_TARGET)
        warnings.append(
            f"{unmapped} entr{'y' if unmapped == 1 else 'ies'} skipped: "
            f"no value for the key mapped to Device name ('{name_source}')"
        )
    names = [record.mapped["name"] for record in records]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates and file_format == "csv":
        warnings.append(
            f"Several lines share the same name ({', '.join(duplicates[:3])}): enable "
            "'Multiple lines per device' to merge them"
        )
    return warnings
