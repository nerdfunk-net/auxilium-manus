"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-operations"])


def get_cached_commits(
    git_cache_service, repo_id: int, branch_name: str, repo_path: str, limit: int = 50
):
    """
    Get commits for a repository using cache when available.

    DEPRECATED: This function now delegates to git_cache_service.
    """
    return git_cache_service.get_commits(
        repo_id=repo_id,
        repo_path=repo_path,
        branch_name=branch_name,
        limit=limit,
        use_models=False,  # Return dicts for backward compatibility
    )


@router.get("/status")
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
    except Exception as e:
        logger.error("Error getting repository status: %s", e)
        return {
            "success": False,
            "message": f"Failed to get repository status: {str(e)}",
        }


@router.post("/sync")
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

        git_repo_manager.update_sync_status(repo_id, f"error: {result.message}")
        raise_internal_server_error(logger, result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error syncing repository", e)


@router.post("/remove-and-sync")
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

        git_repo_manager.update_sync_status(repo_id, f"error: {result.message}")
        raise_internal_server_error(logger, result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing and syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error removing and syncing repository", e)


@router.get("/info")
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


@router.get("/debug")
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
    except Exception as e:
        return {"status": "error", "error": str(e), "error_type": type(e).__name__}
