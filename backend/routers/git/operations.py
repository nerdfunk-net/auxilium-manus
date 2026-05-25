"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging
import os
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError, Repo

from core.auth import get_current_user
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_git_auth_service,
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.env import set_ssl_env
from services.git.paths import repo_path as git_repo_path
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
    git_auth_service=Depends(get_git_auth_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Sync a git repository (clone if not exists, pull if exists)."""
    try:
        # Load repository
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "syncing")

        # Compute repo path (uses configured 'path' or fallback to 'name')
        repo_path = str(git_repo_path(repository))

        logger.info(
            "Syncing repository '%s' to path: %s", repository["name"], repo_path
        )
        logger.info("Repository URL: %s", repository["url"])
        logger.info("Repository branch: %s", repository["branch"])

        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        # Determine action: clone or pull
        repo_dir_exists = os.path.exists(repo_path)
        is_git_repo = os.path.isdir(os.path.join(repo_path, ".git"))
        needs_clone = not is_git_repo

        success = False
        message = ""

        # Use authentication service for all auth operations
        with git_auth_service.setup_auth_environment(repository) as (
            clone_url,
            resolved_username,
            resolved_token,
            ssh_key_path,
        ):
            if needs_clone:
                # Backup non-repo directory if present
                if repo_dir_exists and not is_git_repo:
                    parent_dir = os.path.dirname(
                        repo_path.rstrip(os.sep)
                    ) or os.path.dirname(repo_path)
                    base_name = os.path.basename(os.path.normpath(repo_path))
                    backup_path = os.path.join(
                        parent_dir, f"{base_name}_backup_{int(time.time())}"
                    )
                    shutil.move(repo_path, backup_path)
                    logger.info("Backed up existing directory to %s", backup_path)

                # SSL env toggle
                try:
                    if not repository.get("verify_ssl", True):
                        logger.warning(
                            "Git SSL verification disabled - not recommended for production"
                        )
                    with set_ssl_env(repository):
                        logger.info(
                            "Cloning branch %s into %s", repository["branch"], repo_path
                        )
                        Repo.clone_from(
                            clone_url, repo_path, branch=repository["branch"]
                        )

                    if not os.path.isdir(os.path.join(repo_path, ".git")):
                        raise GitCommandError(
                            "clone", 1, b"", b".git not found after clone"
                        )

                    success = True
                    message = f"Repository '{repository['name']}' cloned successfully to {repo_path}"
                    logger.info(message)
                except GitCommandError as gce:
                    err = str(gce)
                    logger.error("Git clone failed: %s", err)
                    if "authentication" in err.lower():
                        message = (
                            "Authentication failed. Please check your Git credentials."
                        )
                    elif "not found" in err.lower():
                        message = f"Repository or branch not found. URL: {repository['url']} Branch: {repository['branch']}"
                    else:
                        message = f"Git clone failed: {err}"
                except Exception as e:
                    logger.error("Unexpected error during Git clone: %s", e)
                    message = f"Unexpected error: {str(e)}"
                finally:
                    # Cleanup empty directory after failed clone
                    try:
                        if (
                            not success
                            and os.path.isdir(repo_path)
                            and not os.listdir(repo_path)
                        ):
                            shutil.rmtree(repo_path)
                            logger.info(
                                "Removed empty directory after failed clone: %s",
                                repo_path,
                            )
                    except Exception as ce:
                        logger.warning("Cleanup after failed clone skipped: %s", ce)
            else:
                # Pull latest
                try:
                    repo = Repo(repo_path)
                    origin = repo.remotes.origin

                    # Update remote URL with authenticated URL if using token auth
                    if resolved_token and "http" in repository["url"]:
                        try:
                            origin.set_url(clone_url)
                        except Exception as e:
                            logger.debug("Skipping remote URL update: %s", e)

                    with set_ssl_env(repository):
                        origin.pull(repository["branch"])
                        success = True
                        message = (
                            f"Repository '{repository['name']}' updated successfully"
                        )
                        logger.info(message)
                except Exception as e:
                    logger.error("Error during Git pull: %s", e)
                    message = f"Pull failed: {str(e)}"

        # Final status
        if success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            # Invalidate cache after successful sync
            git_cache_service.invalidate_repo(repo_id)
            return {"success": True, "message": message, "repository_path": repo_path}
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error", e)


@router.post("/remove-and-sync")
async def remove_and_sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_auth_service=Depends(get_git_auth_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Remove existing repository and clone fresh copy."""
    try:
        # Get repository details
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "removing-and-syncing")

        # Resolve repository working directory
        repo_path = str(git_repo_path(repository))

        logger.info(
            "Remove and sync repository '%s' at path: %s", repository["name"], repo_path
        )

        # Remove existing directory if it exists
        if os.path.exists(repo_path):
            # Create backup with timestamp
            parent_dir = os.path.dirname(repo_path.rstrip(os.sep)) or os.path.dirname(
                repo_path
            )
            base_name = os.path.basename(os.path.normpath(repo_path))
            backup_path = os.path.join(
                parent_dir, f"{base_name}_removed_{int(time.time())}"
            )

            try:
                shutil.move(repo_path, backup_path)
                logger.info("Existing repository backed up to %s", backup_path)
            except Exception as e:
                logger.warning("Could not backup existing repository: %s", e)
                # Try to remove directly
                shutil.rmtree(repo_path, ignore_errors=True)
                logger.info("Removed existing repository at %s", repo_path)

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        # Clone fresh copy using authentication service
        success = False
        message = ""

        with git_auth_service.setup_auth_environment(repository) as (
            clone_url,
            resolved_username,
            resolved_token,
            ssh_key_path,
        ):
            try:
                if not repository.get("verify_ssl", True):
                    logger.warning(
                        "Git SSL verification disabled - not recommended for production"
                    )

                with set_ssl_env(repository):
                    logger.info(
                        "Cloning fresh copy of branch %s into %s",
                        repository["branch"],
                        repo_path,
                    )
                    Repo.clone_from(clone_url, repo_path, branch=repository["branch"])

                if not os.path.isdir(os.path.join(repo_path, ".git")):
                    raise GitCommandError(
                        "clone", 1, b"", b".git not found after clone"
                    )

                success = True
                message = f"Repository '{repository['name']}' removed and re-cloned successfully"
                logger.info(message)

            except GitCommandError as gce:
                err = str(gce)
                logger.error("Git clone failed: %s", err)
                if "authentication" in err.lower():
                    message = (
                        "Authentication failed. Please check your Git credentials."
                    )
                elif "not found" in err.lower():
                    message = f"Repository or branch not found. URL: {repository['url']} Branch: {repository['branch']}"
                else:
                    message = f"Git clone failed: {err}"
            except Exception as e:
                logger.error("Unexpected error during Git clone: %s", e)
                message = f"Unexpected error: {str(e)}"
            finally:
                # Cleanup empty directory after failed clone
                try:
                    if (
                        not success
                        and os.path.isdir(repo_path)
                        and not os.listdir(repo_path)
                    ):
                        shutil.rmtree(repo_path)
                        logger.info(
                            "Removed empty directory after failed clone: %s", repo_path
                        )
                except Exception as ce:
                    logger.warning("Cleanup after failed clone skipped: %s", ce)

        # Final status update
        if success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            # Invalidate cache after successful sync
            git_cache_service.invalidate_repo(repo_id)
            return {"success": True, "message": message, "repository_path": repo_path}
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing and syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error", e)


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
