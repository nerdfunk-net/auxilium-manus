"""
Git version control router - Git VCS operations like branches, commits, and diffs.
Thin wrappers delegating to GitVersionControlService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError, InvalidGitRepositoryError

from core.auth import get_current_user
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_cache_service, get_git_version_control_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-version-control"])


@router.get("/branches")
async def get_branches(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    vc_service=Depends(get_git_version_control_service),
):
    """Get list of Git branches."""
    try:
        return vc_service.get_branches(repo_id)
    except (InvalidGitRepositoryError, GitCommandError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Git repository not found or invalid: {str(e)}",
        ) from e
    except Exception as e:
        raise_internal_server_error(logger, "Git branches error: ", e)


@router.get("/commits/{branch_name}")
async def get_commits(
    repo_id: int,
    branch_name: str,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
    vc_service=Depends(get_git_version_control_service),
):
    """Get commits for a specific branch."""
    try:
        return vc_service.get_commits(repo_id, branch_name, cache_service)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        raise_internal_server_error(logger, "Failed to get commits: ", e)


@router.post("/diff")
async def compare_commits(
    repo_id: int,
    request: dict,
    current_user: dict = Depends(get_current_user),
    vc_service=Depends(get_git_version_control_service),
):
    """Compare files between two Git commits."""
    try:
        commit1 = request.get("commit1")
        commit2 = request.get("commit2")
        file_path = request.get("file_path")

        if not all([commit1, commit2, file_path]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required parameters: commit1, commit2, file_path",
            )

        return vc_service.compare_commits(repo_id, commit1, commit2, file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Failed to compare commits: ", e)
