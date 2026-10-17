"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, require_permission
from core.domain_exceptions import DomainError
from core.rate_limit import rate_limited
from core.safe_http_errors import internal_error_detail, raise_internal_server_error
from dependencies import (
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.operations import SyncExecutionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-operations"])


@router.post(
    "/sync",
    dependencies=[
        Depends(require_permission("git.operations", "execute")),
        Depends(rate_limited("git-sync", attempts=10, window_seconds=60)),
    ],
)
def sync_repository(
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
    dependencies=[
        Depends(require_permission("git.operations", "execute")),
        Depends(rate_limited("git-sync", attempts=10, window_seconds=60)),
    ],
)
def remove_and_sync_repository(
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
