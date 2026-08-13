"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging
import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.safe_http_errors import internal_error_detail, raise_internal_server_error
from dependencies import (
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-operations"])


@router.get("/status", dependencies=[Depends(require_permission("git.operations", "read"))])
async def get_repository_status(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
):
    """Get the status of a specific repository (exists, sync status, commit info).

    This endpoint now uses GitPython instead of subprocess calls for ~50% performance improvement.
    Replaces 7 sequential subprocess calls with a single GitPython Repo instance.
    """
    try:
        # Get repository details
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Use git_operations_service for status (GitPython-based, no subprocess)
        status_info = git_operations_service.get_repository_status(repository, repo_id)

        return {"success": True, "data": status_info}

    except HTTPException:
        raise
    except Exception:
        error_id = str(uuid.uuid4())
        logger.error(
            "Error getting repository status (error_id=%s)",
            error_id,
            exc_info=True,
            extra={"error_id": error_id},
        )
        return {
            "success": False,
            "message": "Failed to get repository status",
            "error_id": error_id,
        }


def _fail_sync_with_error_id(
    repo_id: int, log_message: str, exc: BaseException | None = None
) -> NoReturn:
    """Persist a correlation id on sync_status and raise a sanitized 500."""
    error_id = str(uuid.uuid4())
    if exc is not None:
        logger.error(
            "%s (error_id=%s)",
            log_message,
            error_id,
            exc_info=True,
            extra={"error_id": error_id},
        )
    else:
        logger.error(
            "%s (error_id=%s)",
            log_message,
            error_id,
            extra={"error_id": error_id},
        )
    git_repo_manager.update_sync_status(repo_id, f"error:{error_id}")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=internal_error_detail(error_id=error_id),
    ) from exc


@router.post("/sync", dependencies=[Depends(require_permission("git.operations", "execute"))])
async def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Sync a git repository (clone if not exists, pull if exists)."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "syncing")
        result = git_operations_service.sync_repository(repository)

        if result.success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        _fail_sync_with_error_id(repo_id, f"Sync failed for repository {repo_id}: {result.message}")

    except HTTPException:
        raise
    except Exception as e:
        _fail_sync_with_error_id(repo_id, f"Error syncing repository {repo_id}", e)


@router.post(
    "/remove-and-sync",
    dependencies=[Depends(require_permission("git.operations", "execute"))],
)
async def remove_and_sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Remove existing repository and clone fresh copy."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "removing-and-syncing")
        result = git_operations_service.remove_and_sync(repository)

        if result.success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        _fail_sync_with_error_id(
            repo_id, f"Remove-and-sync failed for repository {repo_id}: {result.message}"
        )

    except HTTPException:
        raise
    except Exception as e:
        _fail_sync_with_error_id(repo_id, f"Error removing and syncing repository {repo_id}", e)


@router.get("/info", dependencies=[Depends(require_permission("git.operations", "read"))])
async def get_repository_info(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get detailed information about a repository."""
    try:
        # Get repository metadata from DB
        repository = git_repo_manager.get_repository(repo_id)

        if not repository:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository with ID {repo_id} not found",
            )

        # Get git repository instance
        repo = get_git_repo_by_id(repo_id)

        # Collect repository statistics
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

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Failed to get repository info: ", e)


@router.get("/debug", dependencies=[Depends(require_permission("git.operations", "read"))])
async def debug_git(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Debug Git setup."""
    try:
        repo = get_git_repo_by_id(repo_id)
        return {
            "status": "success",
            "repo_path": repo.working_dir,
            "branch": repo.active_branch.name,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Git debug failed for repo {repo_id}", e)
