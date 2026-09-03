"""
Git Operations Service - Centralized repository operations.

This service consolidates sync, clone, pull, and status operations that were
previously duplicated or embedded in routers. All real clone/pull/fetch network
operations delegate to ``services.git.service.GitService`` — the single place
that enforces ``core.safe_urls.validate_git_remote_url`` — so status checks and
repository syncing are held to the same URL-safety policy as everything else in
the git subsystem.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from typing import Any

from git import GitCommandError, Repo

from core.domain_exceptions import NotFoundError
from core.safe_urls import UnsafeURLError
from models.git import SyncResult
from services.git.paths import repo_path as get_repo_path
from services.git.repository_service import GitRepositoryService
from services.git.service import GitService
from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)


class SyncExecutionError(RuntimeError):
    """A sync/remove-and-sync operation failed after being recorded on the repo."""

    def __init__(self, error_id: str, log_message: str) -> None:
        super().__init__(log_message)
        self.error_id = error_id


def _empty_repository_status(repository: dict[str, Any], repo_path: str) -> dict[str, Any]:
    return {
        "repository_name": repository["name"],
        "repository_url": repository["url"],
        "repository_branch": repository["branch"],
        "sync_status": repository.get("sync_status", "unknown"),
        "exists": os.path.exists(repo_path),
        "is_git_repo": False,
        "is_synced": False,
        "behind_count": 0,
        "ahead_count": 0,
        "current_commit": None,
        "current_branch": None,
        "last_commit_message": None,
        "last_commit_date": None,
        "branches": [],
        "commits": [],
        "config_files": [],
    }


def _fill_local_git_metadata(repo: Repo, status_info: dict[str, Any]) -> None:
    try:
        status_info["current_branch"] = repo.active_branch.name
    except Exception as e:
        logger.warning("Could not get current branch: %s", e)
        status_info["current_branch"] = "HEAD"

    try:
        if repo.head.is_valid():
            commit = repo.head.commit
            status_info["current_commit"] = commit.hexsha[:8]
            status_info["last_commit_message"] = commit.message.strip()
            status_info["last_commit_date"] = commit.committed_datetime.isoformat()
            status_info["last_commit_author"] = commit.author.name
            status_info["last_commit_author_email"] = commit.author.email
    except Exception as e:
        logger.warning("Could not get commit info: %s", e)

    try:
        status_info["branches"] = [branch.name for branch in repo.branches]
    except Exception as e:
        logger.warning("Could not list branches: %s", e)


def _fill_cached_commits(
    status_info: dict[str, Any],
    repo_id: int,
    repo_path: str,
    branch: str,
) -> None:
    try:
        import service_factory

        git_cache_service = service_factory.build_git_cache_service()
        status_info["commits"] = git_cache_service.get_commits(
            repo_id=repo_id,
            repo_path=repo_path,
            branch_name=branch,
            limit=50,
            use_models=False,
        )
    except Exception as e:
        logger.warning("Could not get recent commits: %s", e)
        status_info["commits"] = []


def _fill_remote_sync_status(
    git_service: GitService,
    repository: dict[str, Any],
    repo: Repo,
    status_info: dict[str, Any],
    branch: str,
) -> None:
    try:
        if "origin" not in [r.name for r in repo.remotes]:
            return

        fetch_result = git_service.fetch(repository, repo=repo)
        if not fetch_result.success:
            logger.debug("Fetch failed: %s", fetch_result.message)

        try:
            remote_branch = f"origin/{branch}"
            if remote_branch in [ref.name for ref in repo.refs]:
                behind = list(repo.iter_commits(f"HEAD..{remote_branch}", max_count=100))
                status_info["behind_count"] = len(behind)

                ahead = list(repo.iter_commits(f"{remote_branch}..HEAD", max_count=100))
                status_info["ahead_count"] = len(ahead)

                status_info["is_synced"] = status_info["behind_count"] == 0
        except Exception as rev_error:
            logger.debug("Could not calculate ahead/behind: %s", rev_error)
    except Exception as e:
        logger.warning("Could not check sync status: %s", e)
        status_info["is_synced"] = False


def _sync_needs_clone(*, force_clone: bool, is_git_repo: bool) -> bool:
    return force_clone or not is_git_repo


def _map_clone_error_message(err: str, repository: dict[str, Any]) -> str:
    if "authentication" in err.lower():
        return "Authentication failed. Please check your Git credentials."
    if "not found" in err.lower():
        return (
            f"Repository or branch not found. "
            f"URL: {repository['url']} Branch: {repository['branch']}"
        )
    return f"Git clone failed: {err}"


def _backup_non_git_directory(
    repo_path: str, *, repo_dir_exists: bool, is_git_repo: bool
) -> None:
    if repo_dir_exists and not is_git_repo:
        parent_dir = os.path.dirname(repo_path.rstrip(os.sep)) or os.path.dirname(repo_path)
        base_name = os.path.basename(os.path.normpath(repo_path))
        backup_path = os.path.join(parent_dir, f"{base_name}_backup_{int(time.time())}")
        shutil.move(repo_path, backup_path)
        logger.info("Backed up existing directory to %s", backup_path)


def _scan_config_files(repo_path: str) -> list[str]:
    config_files: list[str] = []
    for root, _dirs, files in os.walk(repo_path):
        if ".git" in root:
            continue
        for file in files:
            if not file.startswith("."):
                rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                config_files.append(rel_path)
    config_files.sort()
    return config_files


class GitOperationsService:
    """Service for git repository operations like sync, clone, pull, and status.

    Delegates all real clone/pull/fetch network operations to the shared
    ``GitService`` engine (services/git/service.py) — the single place that
    enforces ``core.safe_urls.validate_git_remote_url``.
    """

    def __init__(self, repos: GitRepositoryService | None = None):
        self._git_service = GitService()
        self._repos = repos or GitRepositoryService()

    def sync_repository(self, repository: dict[str, Any], force_clone: bool = False) -> SyncResult:
        """Sync a repository (clone if not exists, pull if exists).

        Args:
            repository: Repository metadata dict
            force_clone: If True, remove existing repo and clone fresh

        Returns:
            SyncResult with success status and message
        """
        repo_path = str(get_repo_path(repository))
        logger.info("Syncing repository '%s' to path: %s", repository["name"], repo_path)
        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        repo_dir_exists = os.path.exists(repo_path)
        is_git_repo = os.path.isdir(os.path.join(repo_path, ".git"))
        needs_clone = _sync_needs_clone(force_clone=force_clone, is_git_repo=is_git_repo)

        if needs_clone:
            _backup_non_git_directory(
                repo_path, repo_dir_exists=repo_dir_exists, is_git_repo=is_git_repo
            )
            try:
                self._git_service.clone(repository)
                success = True
                message = f"Repository '{repository['name']}' cloned successfully to {repo_path}"
                logger.info(message)
            except UnsafeURLError as exc:
                success = False
                message = f"Repository URL is not allowed: {exc}"
                logger.warning(message)
            except GitCommandError as exc:
                success = False
                message = _map_clone_error_message(str(exc), repository)
                logger.error("Git clone failed: %s", exc)
            except Exception as exc:
                success = False
                message = f"Unexpected error: {exc}"
                logger.error("Unexpected error during Git clone: %s", exc)
        else:
            pull_result = self._git_service.pull(repository)
            success, message = pull_result.success, pull_result.message

        return SyncResult(
            success=success,
            message=message,
            commits_behind=0,
            commits_ahead=0,
            repository_path=repo_path if success else None,
        )

    def remove_and_sync(self, repository: dict[str, Any]) -> SyncResult:
        """Remove any existing local copy and clone fresh.

        Args:
            repository: Repository metadata dict

        Returns:
            SyncResult with success status and message
        """
        repo_path = str(get_repo_path(repository))
        logger.info(
            "Removing and re-syncing repository '%s' at %s",
            repository["name"],
            repo_path,
        )

        try:
            self._git_service.clone(repository)
            success = True
            message = f"Repository '{repository['name']}' removed and re-cloned successfully"
            logger.info(message)
        except UnsafeURLError as exc:
            success = False
            message = f"Repository URL is not allowed: {exc}"
            logger.warning(message)
        except GitCommandError as exc:
            success = False
            message = _map_clone_error_message(str(exc), repository)
            logger.error("Git clone failed: %s", exc)
        except Exception as exc:
            success = False
            message = f"Unexpected error: {exc}"
            logger.error("Unexpected error during Git clone: %s", exc)

        return SyncResult(
            success=success,
            message=message,
            commits_behind=0,
            commits_ahead=0,
            repository_path=repo_path if success else None,
        )

    def get_repository_status(self, repository: dict[str, Any], repo_id: int) -> dict[str, Any]:
        """Get comprehensive repository status using GitPython."""
        repo_path = str(get_repo_path(repository))
        status_info = _empty_repository_status(repository, repo_path)

        if not status_info["exists"]:
            return status_info

        try:
            repo = Repo(repo_path)
            status_info["is_git_repo"] = True
            _fill_local_git_metadata(repo, status_info)
            _fill_cached_commits(status_info, repo_id, repo_path, repository["branch"])
            _fill_remote_sync_status(
                self._git_service, repository, repo, status_info, repository["branch"]
            )
            try:
                status_info["config_files"] = _scan_config_files(repo_path)
            except Exception as e:
                logger.warning("Could not scan config files: %s", e)
        except Exception as e:
            logger.warning("Error checking Git repository status: %s", e)

        return status_info

    def get_status_payload(self, repo_id: int) -> dict[str, Any]:
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise NotFoundError("Repository not found")
        status_info = self.get_repository_status(repository, repo_id)
        return {"success": True, "data": status_info}

    def sync_and_record(self, repo_id: int, git_cache_service: Any) -> dict[str, Any]:
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise NotFoundError("Repository not found")

        self._repos.update_sync_status(repo_id, "syncing")
        result = self.sync_repository(repository)

        if result.success:
            self._repos.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        error_id = str(uuid.uuid4())
        self._repos.update_sync_status(repo_id, f"error:{error_id}")
        logger.error(
            "Sync failed for repository %s: %s (error_id=%s)", repo_id, result.message, error_id
        )
        raise SyncExecutionError(
            error_id, f"Sync failed for repository {repo_id}: {result.message}"
        )

    def remove_and_sync_and_record(self, repo_id: int, git_cache_service: Any) -> dict[str, Any]:
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise NotFoundError("Repository not found")

        self._repos.update_sync_status(repo_id, "removing-and-syncing")
        result = self.remove_and_sync(repository)

        if result.success:
            self._repos.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        error_id = str(uuid.uuid4())
        self._repos.update_sync_status(repo_id, f"error:{error_id}")
        logger.error(
            "Remove-and-sync failed for repository %s: %s (error_id=%s)",
            repo_id,
            result.message,
            error_id,
        )
        raise SyncExecutionError(
            error_id, f"Remove-and-sync failed for repository {repo_id}: {result.message}"
        )

    def get_info_payload(self, repo_id: int) -> dict[str, Any]:
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise NotFoundError(f"Repository with ID {repo_id} not found")

        repo = get_git_repo_by_id(repo_id, self._repos)

        try:
            total_commits = sum(1 for _ in repo.iter_commits())
        except (AttributeError, OSError, ValueError):
            total_commits = 0

        try:
            total_branches = len(list(repo.branches))
        except (AttributeError, OSError):
            total_branches = 0

        try:
            current_branch = repo.active_branch.name if repo.active_branch else None
        except (AttributeError, TypeError):
            current_branch = None

        return {
            "id": repository["id"],
            "name": repository["name"],
            "category": repository["category"],
            "url": repository["url"],
            "branch": repository["branch"],
            "path": repository.get("path"),
            "is_active": repository["is_active"],
            "description": repository.get("description"),
            "created_at": repository.get("created_at"),
            "last_sync": repository.get("last_sync"),
            "sync_status": repository.get("sync_status"),
            "git_stats": {
                "current_branch": current_branch,
                "total_commits": total_commits,
                "total_branches": total_branches,
                "working_directory": repo.working_dir,
            },
        }

    def get_debug_payload(self, repo_id: int) -> dict[str, Any]:
        repo = get_git_repo_by_id(repo_id, self._repos)
        return {
            "status": "success",
            "repo_path": repo.working_dir,
            "branch": repo.active_branch.name,
        }
