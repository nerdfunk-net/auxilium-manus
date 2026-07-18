"""
Git repository management router - CRUD operations for repositories.
Handles creation, reading, updating, and deletion of Git repository configurations.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, require_permission
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_git_connection_service
from models.git_repositories import (
    GitConnectionTestRequest,
    GitConnectionTestResponse,
    GitRepositoryListResponse,
    GitRepositoryRequest,
    GitRepositoryResponse,
    GitRepositoryUpdateRequest,
)
from services.git.shared_utils import git_repo_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git-repositories", tags=["git-repositories"])


@router.get(
    "/",
    response_model=GitRepositoryListResponse,
    dependencies=[Depends(require_permission("git.repositories", "read"))],
)
async def get_repositories(
    category: Optional[str] = None,
    active_only: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Get all git repositories."""
    try:
        repositories = git_repo_manager.get_repositories(
            category=category, active_only=active_only
        )

        # Convert to response models
        repo_responses = []
        for repo in repositories:
            repo_responses.append(GitRepositoryResponse(**dict(repo)))

        return GitRepositoryListResponse(
            repositories=repo_responses, total=len(repo_responses)
        )
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.get(
    "/{repo_id}",
    response_model=GitRepositoryResponse,
    dependencies=[Depends(require_permission("git.repositories", "read"))],
)
async def get_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get a specific git repository by ID."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Convert repository data
        repo_dict = dict(repository)

        return GitRepositoryResponse(**repo_dict)
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.get(
    "/{repo_id}/edit",
    dependencies=[Depends(require_permission("git.repositories", "read"))],
)
async def get_repository_for_edit(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get a specific git repository by ID with all fields for editing."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Return all fields including token for editing purposes
        return repository
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.post(
    "/",
    response_model=GitRepositoryResponse,
    dependencies=[Depends(require_permission("git.repositories", "write"))],
)
async def create_repository(
    repository: GitRepositoryRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new git repository."""
    try:
        repo_data = repository.dict()
        # Remove legacy username/token fields - only use credential_name
        repo_data.pop("username", None)
        repo_data.pop("token", None)
        repo_id = git_repo_manager.create_repository(repo_data)

        # Get the created repository
        created_repo = git_repo_manager.get_repository(repo_id)
        if not created_repo:
            raise HTTPException(
                status_code=500, detail="Failed to retrieve created repository"
            )

        # Convert created repository data
        repo_dict = dict(created_repo)

        return GitRepositoryResponse(**repo_dict)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.put(
    "/{repo_id}",
    response_model=GitRepositoryResponse,
    dependencies=[Depends(require_permission("git.repositories", "write"))],
)
async def update_repository(
    repo_id: int,
    repository: GitRepositoryUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update a git repository."""
    try:
        # Check if repository exists
        existing_repo = git_repo_manager.get_repository(repo_id)
        if not existing_repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Update only provided fields
        repo_data = {k: v for k, v in repository.dict().items() if v is not None}
        # Remove legacy username/token fields - only use credential_name
        repo_data.pop("username", None)
        repo_data.pop("token", None)

        if not repo_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        success = git_repo_manager.update_repository(repo_id, repo_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update repository")

        # Get the updated repository
        updated_repo = git_repo_manager.get_repository(repo_id)
        if not updated_repo:
            raise HTTPException(
                status_code=500, detail="Failed to retrieve updated repository"
            )

        # Convert updated repository data
        repo_dict = dict(updated_repo)

        return GitRepositoryResponse(**repo_dict)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.delete(
    "/{repo_id}",
    dependencies=[Depends(require_permission("git.repositories", "delete"))],
)
async def delete_repository(
    repo_id: int,
    hard_delete: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """Delete a git repository."""
    try:
        # Check if repository exists
        existing_repo = git_repo_manager.get_repository(repo_id)
        if not existing_repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        success = git_repo_manager.delete_repository(repo_id, hard_delete=hard_delete)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete repository")

        action = "deleted" if hard_delete else "deactivated"
        return {"message": f"Repository {action} successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.post(
    "/test-connection",
    response_model=GitConnectionTestResponse,
    dependencies=[Depends(require_permission("git.repositories", "read"))],
)
async def test_git_connection(
    test_request: GitConnectionTestRequest,
    current_user: dict = Depends(get_current_user),
    git_connection_service=Depends(get_git_connection_service),
):
    """Test git repository connection.

    This endpoint now uses git_connection_service for all connection testing logic.
    The service handles credential resolution, authentication setup, and shallow clone testing.
    """
    logger.info(
        "Received test connection request from user: %s",
        current_user.username,
    )
    logger.debug(
        "Test request details: url=%s, branch=%s, auth_type=%s, credential_name=%s",
        test_request.url,
        test_request.branch,
        test_request.auth_type,
        test_request.credential_name,
    )

    try:
        result = git_connection_service.test_connection(test_request)
        logger.info(
            "Test connection result: success=%s, message=%s",
            result.success,
            result.message,
        )
        return result
    except Exception as e:
        logger.error("Exception in test_git_connection endpoint: %s", e, exc_info=True)
        raise


@router.get(
    "/health",
    dependencies=[Depends(require_permission("git.repositories", "read"))],
)
async def health_check(
    current_user: dict = Depends(get_current_user),
):
    """Health check for git repository management."""
    try:
        health = git_repo_manager.health_check()
        return health
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)
