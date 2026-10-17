"""
Shared Git utilities for use across Git router modules.
Consolidates common functions to avoid duplication.
"""

import logging

from core.domain_exceptions import NotFoundError, ValidationFailedError
from services.git.repository_service import GitRepositoryService

logger = logging.getLogger(__name__)


def get_git_repo_by_id(repo_id: int, repos: GitRepositoryService | None = None):
    """Get Git repository instance by ID (shared utility function)."""
    repos = repos or GitRepositoryService()

    # Get repository details directly by ID
    repository = repos.get_repository(repo_id)

    if not repository:
        raise NotFoundError(f"Git repository with ID {repo_id} not found.")

    if not repository["is_active"]:
        raise ValidationFailedError(
            f"Git repository '{repository['name']}' is inactive. Please activate it first."
        )

    # Open the repository (or clone if needed) using central git_service
    try:
        import service_factory

        return service_factory.build_git_service().open_or_clone(repository)
    except Exception as e:
        logger.exception("Failed to open/clone Git repository %s", repository["name"])
        raise RuntimeError(f"Failed to open/clone Git repository {repository['name']}") from e
