"""Git source service — clone/pull a repository and extract device data from YAML files.

All real git operations (clone/pull/push/test-connection) delegate to the shared
``services.git`` engine (``GitService`` for clone/pull, ``GitConnectionService`` for
connection testing) — the same engine ``store-artifact``/``git-push``/the Git Repositories
feature use — so there is a single place that talks to git and a single place that enforces
``core.safe_urls.validate_git_remote_url``.
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import Any

import yaml

from core.safe_urls import UnsafeURLError
from git import GitCommandError
from models.git_repositories import GitAuthType, GitConnectionTestRequest
from services.git.connection import GitConnectionService

logger = logging.getLogger(__name__)


def source_config_to_git_repository(source_config: dict[str, Any]) -> dict[str, Any]:
    """Map a resolved Settings git-source config to a ``GitService`` repository dict."""
    source_id: str = source_config["source_id"]
    on_disk_path = str(source_config.get("repository_path") or source_id).strip("/\\") or source_id
    return {
        "id": source_id,
        "name": source_id,
        "url": str(source_config.get("url") or "").strip(),
        "branch": str(source_config.get("branch") or "main").strip() or "main",
        "auth_type": "token",
        "token": str(source_config.get("token") or "").strip(),
        "username": str(source_config.get("username") or "").strip(),
        "path": on_disk_path,
        "verify_ssl": bool(source_config.get("verify_ssl", True)),
        "source_id": source_id,
    }


def test_connection(
    *,
    url: str,
    branch: str = "main",
    username: str = "",
    token: str = "",
    verify_ssl: bool = True,
) -> dict[str, Any]:
    """Test connectivity to a Settings git source via the shared ``GitConnectionService``.

    Thin adapter: builds a ``GitConnectionTestRequest`` (always inline-token auth, matching
    how Settings git sources store credentials) and translates the response back to the
    ``{success, message}`` shape this module's callers expect.
    """
    branch_name = (branch or "main").strip() or "main"
    request = GitConnectionTestRequest(
        url=(url or "").strip(),
        branch=branch_name,
        auth_type=GitAuthType.TOKEN,
        username=(username or "").strip() or None,
        token=(token or "").strip() or None,
        verify_ssl=verify_ssl,
    )

    response = GitConnectionService().test_connection(request)

    if response.success:
        return {
            "success": True,
            "message": f"Connection successful (branch '{branch_name}')",
        }

    error_detail = (response.details or {}).get("error")
    message = f"{response.message}: {error_detail}" if error_detail else response.message
    return {"success": False, "message": message}


def clone_or_pull(source_config: dict[str, Any]) -> Path:
    """Ensure the repository is available locally; return the root path.

    Delegates to the shared ``GitService`` engine. A pull failure on an already-cloned
    repo is logged and swallowed — the cached copy is used — matching the previous
    behaviour of this function.
    """
    source_id: str = source_config["source_id"]
    if not str(source_config.get("url") or "").strip():
        raise ValueError(f"Git source '{source_id}' has no URL configured")

    repository = source_config_to_git_repository(source_config)

    import service_factory

    git_service = service_factory.build_git_service()
    repo_dir = git_service.get_repo_path(repository)
    repo_existed = (repo_dir / ".git").is_dir()

    try:
        repo = git_service.open_or_clone(repository)
    except UnsafeURLError as exc:
        raise ValueError(f"Git source '{source_id}' has an unsafe URL: {exc}") from exc
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to clone git source '{source_id}': {exc}") from exc

    if repo_existed:
        pull_result = git_service.pull(repository, repo=repo)
        if pull_result.success:
            logger.info(
                "Pulled git source '%s' branch '%s'", source_id, repository["branch"]
            )
        else:
            logger.warning(
                "Pull failed for '%s': %s — using cached copy",
                source_id,
                pull_result.message,
            )
    else:
        logger.info("Cloned git source '%s'", source_id)

    return repo_dir


def remove_and_clone(source_config: dict[str, Any]) -> Path:
    """Remove any existing local copy and clone fresh; return the root path."""
    source_id: str = source_config["source_id"]
    if not str(source_config.get("url") or "").strip():
        raise ValueError(f"Git source '{source_id}' has no URL configured")

    repository = source_config_to_git_repository(source_config)

    import service_factory

    git_service = service_factory.build_git_service()
    try:
        git_service.clone(repository)
    except UnsafeURLError as exc:
        raise ValueError(f"Git source '{source_id}' has an unsafe URL: {exc}") from exc
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to clone git source '{source_id}': {exc}") from exc

    logger.info("Cloned git source '%s'", source_id)
    return git_service.get_repo_path(repository)


def _find_files(repo_dir: Path, repository_path: str, pattern: str) -> list[Path]:
    """Return all files in the repo that match *pattern* (glob syntax)."""
    # Strip leading slashes — pathlib treats "/" as absolute, which would escape the repo root.
    clean_path = repository_path.lstrip("/\\")
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

    Call directly from async handlers (same pattern as cockpit-ng) — GitPython
    manages its own subprocess lifecycle and does not need an executor wrapper.
    """

    def fetch_devices(
        self, source_config: dict[str, Any], filename_pattern: str
    ) -> tuple[list[dict[str, Any]], int]:
        """Clone/pull the repo, find matching files, and parse device entries.

        Returns a tuple of (devices, files_read).
        """
        source_id = source_config.get("source_id")
        logger.info(
            "[DEBUG] fetch_devices START — source=%s pattern=%s", source_id, filename_pattern
        )

        repo_dir = clone_or_pull(source_config)
        logger.info("[DEBUG] fetch_devices — clone_or_pull returned repo_dir=%s", repo_dir)

        repository_path = source_config.get("repository_path", "").strip()
        logger.info(
            "[DEBUG] fetch_devices — calling _find_files with root=%s path=%r pattern=%s",
            repo_dir,
            repository_path,
            filename_pattern,
        )
        if repository_path.startswith(("/", "\\")):
            logger.warning(
                "Git source '%s': repository_path %r starts with a slash — "
                "it will be treated as relative to the repo root",
                source_id,
                repository_path,
            )

        files = _find_files(repo_dir, repository_path, filename_pattern)
        logger.info(
            "Git source '%s': found %d file(s) matching '%s'",
            source_id,
            len(files),
            filename_pattern,
        )
        logger.info("[DEBUG] fetch_devices — files found: %s", [str(f) for f in files])

        devices: list[dict[str, Any]] = []
        for file_path in files:
            logger.info("[DEBUG] fetch_devices — parsing file: %s", file_path)
            parsed = _parse_yaml_file(file_path)
            logger.info(
                "[DEBUG] fetch_devices — parsed %d device(s) from %s", len(parsed), file_path
            )
            devices.extend(parsed)

        logger.info(
            "[DEBUG] fetch_devices DONE — returning %d device(s) from %d file(s)",
            len(devices),
            len(files),
        )
        return devices, len(files)
