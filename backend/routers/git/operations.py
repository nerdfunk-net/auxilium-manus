"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, require_permission
from core.domain_exceptions import DomainError
from core.safe_http_errors import internal_error_detail, raise_internal_server_error
from dependencies import (
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.operations import SyncExecutionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-operations"])


@router.get("/status", dependencies=[Depends(require_permission("git.operations", "read"))])
async def get_repository_status(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
):
    """Get the status of a specific repository (exists, sync status, commit info)."""
    try:
        return git_operations_service.get_status_payload(repo_id)
    except DomainError:
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


@router.post("/sync", dependencies=[Depends(require_permission("git.operations", "execute"))])
async def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Sync a git repository (clone if not exists, pull if exists)."""
    try:
        return git_operations_service.sync_and_record(repo_id, git_cache_service)
    except SyncExecutionError as e:
        raise HTTPException(
            status_code=500,
            detail=internal_error_detail(error_id=e.error_id),
        ) from e
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Error syncing repository {repo_id}", e)


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
        return git_operations_service.remove_and_sync_and_record(repo_id, git_cache_service)
    except SyncExecutionError as e:
        raise HTTPException(
            status_code=500,
            detail=internal_error_detail(error_id=e.error_id),
        ) from e
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Error removing and syncing repository {repo_id}", e)


@router.get("/info", dependencies=[Depends(require_permission("git.operations", "read"))])
async def get_repository_info(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
):
    """Get detailed information about a repository."""
    try:
        return git_operations_service.get_info_payload(repo_id)
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Failed to get repository info: ", e)


@router.get("/debug", dependencies=[Depends(require_permission("git.operations", "read"))])
async def debug_git(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
):
    """Debug Git setup."""
    try:
        return git_operations_service.get_debug_payload(repo_id)
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Git debug failed for repo {repo_id}", e)
