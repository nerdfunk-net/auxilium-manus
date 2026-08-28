"""Fetch device data (YAML inventory files) from a git repository."""

from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import Any

import yaml

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


def _parse_device_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name", "")
    if not name:
        return None
    primary_ip4_raw = entry.get("primary_ip4", "")
    network_driver = entry.get("network_driver", "")
    return {
        "id": None,
        "name": str(name),
        "primary_ip4": {"address": str(primary_ip4_raw)} if primary_ip4_raw else None,
        "platform": {
            "name": None,
            "manufacturer": None,
            "network_driver": str(network_driver) if network_driver else None,
        },
    }


def _parse_yaml_file(path: Path) -> list[dict[str, Any]]:
    """Read a YAML file and return a list of device detail dicts."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning("Cannot parse YAML file %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    raw_devices = data.get("devices", [])
    if isinstance(raw_devices, dict):
        raw_devices = [raw_devices]
    if not isinstance(raw_devices, list):
        return []

    results = []
    for entry in raw_devices:
        parsed = _parse_device_entry(entry)
        if parsed is not None:
            results.append(parsed)
    return results


class GitDeviceService:
    """Fetches device data from a git repository.

    Call directly from async handlers — GitPython manages its own subprocess
    lifecycle and does not need an executor wrapper.
    """

    def fetch_devices(
        self, repository: dict[str, Any], filename_pattern: str, directory: str = ""
    ) -> tuple[list[dict[str, Any]], int]:
        """Clone/pull the repo, find matching files, and parse device entries.

        Args:
            repository: A ``GitRepository``-shaped dict (see
                ``GitRepositoryService._to_dict``).
            filename_pattern: Glob pattern for files to search (e.g. ``*.yaml``).
            directory: Subdirectory within the repository to search.

        Returns a tuple of (devices, files_read).
        """
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

        devices: list[dict[str, Any]] = []
        for file_path in files:
            devices.extend(_parse_yaml_file(file_path))

        logger.info(
            "fetch_devices DONE — repo=%s devices=%d files=%d", name, len(devices), len(files)
        )
        return devices, len(files)
