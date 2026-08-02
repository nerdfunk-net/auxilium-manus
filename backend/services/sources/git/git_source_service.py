"""Git source service — clone/pull a repository and extract device data from YAML files."""

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote as urlquote
from urllib.parse import urlparse, urlunparse

import yaml

from core.config import PROJECT_ROOT
from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError
from services.git.env import set_ssl_env

logger = logging.getLogger(__name__)

_GIT_BASE_DIR = PROJECT_ROOT / "data" / "git"
_TEST_CLONE_TIMEOUT_SECONDS = 30


def _build_auth_url(url: str, username: str, token: str) -> str:
    """Inject HTTP basic-auth credentials into an https URL."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not token:
            return url
        user_enc = urlquote(username or "git", safe="")
        token_enc = urlquote(token, safe="")
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@", 1)[-1]
        netloc = f"{user_enc}:{token_enc}@{netloc}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, ""))
    except Exception:
        return url


def _redact_secrets(message: str, *, auth_url: str, public_url: str, token: str) -> str:
    """Strip credentials from git error text before returning to the client."""
    redacted = message.replace(auth_url, public_url)
    if token:
        redacted = redacted.replace(token, "***")
    return redacted


def test_connection(
    *,
    url: str,
    branch: str = "main",
    username: str = "",
    token: str = "",
    verify_ssl: bool = True,
) -> dict[str, Any]:
    """Shallow-clone into a temp directory to verify URL, branch, and credentials.

    Does not touch ``data/git/<source_id>``. Returns ``{success, message}``.
    """
    public_url = url.strip()
    branch_name = (branch or "main").strip() or "main"
    user = (username or "").strip()
    secret = (token or "").strip()

    if not public_url:
        return {"success": False, "message": "Repository URL is required"}

    auth_url = _build_auth_url(public_url, user, secret)
    ssl_config = {"verify_ssl": verify_ssl}

    try:
        with tempfile.TemporaryDirectory(prefix="git-source-test-") as temp_dir:
            clone_path = Path(temp_dir) / "repo"
            cmd = [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch_name,
                auth_url,
                str(clone_path),
            ]
            with set_ssl_env(ssl_config):
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=os.environ.copy(),
                    timeout=_TEST_CLONE_TIMEOUT_SECONDS,
                )
            if result.returncode != 0:
                raw = (result.stderr or result.stdout or "clone failed").strip()
                safe = _redact_secrets(
                    raw, auth_url=auth_url, public_url=public_url, token=secret
                )
                logger.warning("Git source connection test failed: %s", safe)
                return {"success": False, "message": f"Git connection failed: {safe}"}

        logger.info(
            "Git source connection test succeeded url=%s branch=%s",
            public_url,
            branch_name,
        )
        return {
            "success": True,
            "message": f"Connection successful (branch '{branch_name}')",
        }
    except subprocess.TimeoutExpired:
        logger.warning("Git source connection test timed out url=%s", public_url)
        return {
            "success": False,
            "message": f"Git connection test timed out after {_TEST_CLONE_TIMEOUT_SECONDS} seconds",
        }
    except Exception as exc:
        safe = _redact_secrets(
            str(exc), auth_url=auth_url, public_url=public_url, token=secret
        )
        logger.error("Git source connection test error: %s", safe)
        return {"success": False, "message": f"Git connection test error: {safe}"}


def clone_or_pull(source_config: dict[str, Any]) -> Path:
    """Ensure the repository is available locally; return the root path."""
    source_id: str = source_config["source_id"]
    url: str = source_config.get("url", "").strip()
    branch: str = source_config.get("branch", "main").strip() or "main"
    token: str = source_config.get("token", "").strip()
    username: str = source_config.get("username", "").strip()

    if not url:
        raise ValueError(f"Git source '{source_id}' has no URL configured")

    repo_dir = _GIT_BASE_DIR / source_id
    auth_url = _build_auth_url(url, username, token)
    repo_path = str(repo_dir)

    repo_dir_exists = repo_dir.exists()
    is_git_repo = (repo_dir / ".git").is_dir()

    if repo_dir_exists and is_git_repo:
        try:
            repo = Repo(repo_path)
            origin = repo.remotes.origin
            if token and "http" in url:
                try:
                    origin.set_url(auth_url)
                except Exception as exc:
                    logger.info("Skipping remote URL update: %s", exc)
            with set_ssl_env(source_config):
                origin.pull(branch)
            logger.info("Pulled git source '%s' branch '%s'", source_id, branch)
        except InvalidGitRepositoryError:
            logger.warning("Directory %s is not a valid git repo; re-cloning", repo_dir)
            shutil.rmtree(repo_path, ignore_errors=True)
            is_git_repo = False
        except GitCommandError as exc:
            logger.warning("Pull failed for '%s': %s — using cached copy", source_id, exc)
        return repo_dir

    repo_dir.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("Cloning git source '%s' branch '%s' into %s", source_id, branch, repo_dir)
        with set_ssl_env(source_config):
            Repo.clone_from(auth_url, repo_path, branch=branch)
        logger.info("Cloned git source '%s'", source_id)
    except GitCommandError as exc:
        shutil.rmtree(repo_path, ignore_errors=True)
        raise RuntimeError(f"Failed to clone git source '{source_id}': {exc}") from exc

    return repo_dir


def remove_and_clone(source_config: dict[str, Any]) -> Path:
    """Remove any existing local copy and clone fresh; return the root path."""
    source_id: str = source_config["source_id"]
    url: str = source_config.get("url", "").strip()
    branch: str = source_config.get("branch", "main").strip() or "main"
    token: str = source_config.get("token", "").strip()
    username: str = source_config.get("username", "").strip()

    if not url:
        raise ValueError(f"Git source '{source_id}' has no URL configured")

    repo_dir = _GIT_BASE_DIR / source_id
    auth_url = _build_auth_url(url, username, token)
    repo_path = str(repo_dir)

    if repo_dir.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.info("Removed existing local copy of git source '%s'", source_id)

    repo_dir.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("Cloning git source '%s' branch '%s' into %s", source_id, branch, repo_dir)
        with set_ssl_env(source_config):
            Repo.clone_from(auth_url, repo_path, branch=branch)
        logger.info("Cloned git source '%s'", source_id)
    except GitCommandError as exc:
        shutil.rmtree(repo_path, ignore_errors=True)
        raise RuntimeError(f"Failed to clone git source '{source_id}': {exc}") from exc

    return repo_dir


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
