"""
Shared Git utilities for use across Git router modules.
Consolidates common functions to avoid duplication.
"""

import logging

from fastapi import HTTPException, status

from core.safe_http_errors import raise_internal_server_error
from services.git.repository_service import (
    GitRepositoryService as GitRepositoryManager,
)

logger = logging.getLogger(__name__)

# Initialize git repository manager - shared instance
git_repo_manager = GitRepositoryManager()


def get_git_repositories_by_category(category: str):
    """Get all active Git repository instances for a specific category.

    Returns a list of opened/cloned git.Repo objects ready for use.
    """
    import service_factory

    repos = git_repo_manager.get_repositories_by_category(category)
    git_service = service_factory.build_git_service()

    result = []
    for repo_dict in repos:
        try:
            repo = git_service.open_or_clone(repo_dict)
            result.append(repo)
        except Exception as e:
            logger.error("Failed to open/clone repository %s: %s", repo_dict.get("name"), e)
    return result


def get_git_repo_by_id(repo_id: int):
    """Get Git repository instance by ID (shared utility function)."""
    try:
        # Get repository details directly by ID
        repository = git_repo_manager.get_repository(repo_id)

        if not repository:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Git repository with ID {repo_id} not found.",
            )

        if not repository["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Git repository '{repository['name']}' is inactive. Please activate it first.",
            )

        # Open the repository (or clone if needed) using central git_service
        try:
            import service_factory

            repo = service_factory.build_git_service().open_or_clone(repository)
            return repo
        except Exception as e:
            raise_internal_server_error(
                logger,
                f"Failed to open/clone Git repository {repository['name']}",
                e,
            )

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Git repository error: ", e)
