"""Git repository CRUD service — manages git_repositories table in PostgreSQL.

Separate from GitService (git operations: clone, sync, pull).
This service only manages the database records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.models import GitRepository
from repositories import GitRepositoryRepository

logger = logging.getLogger(__name__)


class GitRepositoryService:
    """CRUD service for Git repositories in PostgreSQL.

    Separate from GitService (git operations: clone, sync, pull).
    This service only manages the database records.
    """

    def __init__(self) -> None:
        self._repo = GitRepositoryRepository()

    def create_repository(self, repo_data: Dict[str, Any]) -> int:
        """Create a new git repository record. Returns new ID."""
        try:
            if self._repo.name_exists(repo_data["name"]):
                raise ValueError(
                    f"Repository with name '{repo_data['name']}' already exists"
                )

            new_repo = self._repo.create(
                name=repo_data["name"],
                category=repo_data["category"],
                url=repo_data["url"],
                branch=repo_data.get("branch", "main"),
                credential_name=repo_data.get("credential_name"),
                path=repo_data.get("path"),
                verify_ssl=repo_data.get("verify_ssl", True),
                git_author_name=repo_data.get("git_author_name"),
                git_author_email=repo_data.get("git_author_email"),
                description=repo_data.get("description"),
                is_active=repo_data.get("is_active", True),
            )

            logger.info(
                "Created git repository: %s (ID: %s)", repo_data["name"], new_repo.id
            )
            return new_repo.id
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error creating git repository: %s", e)
            raise

    def get_repository(self, repo_id: int) -> Optional[Dict[str, Any]]:
        """Get a git repository by ID."""
        try:
            repo = self._repo.get_by_id(repo_id)
            return self._to_dict(repo) if repo else None
        except Exception as e:
            logger.error("Error getting git repository %s: %s", repo_id, e)
            raise

    def get_repositories(
        self, category: Optional[str] = None, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all git repositories, optionally filtered by category and active status."""
        try:
            if category:
                repos = self._repo.get_by_category(category, active_only)
            elif active_only:
                repos = self._repo.get_all_active()
            else:
                repos = self._repo.get_all()
            return [self._to_dict(r) for r in repos]
        except Exception as e:
            logger.error("Error getting git repositories: %s", e)
            raise

    def get_repositories_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all active repositories for a specific category."""
        return self.get_repositories(category=category, active_only=True)

    def update_repository(self, repo_id: int, repo_data: Dict[str, Any]) -> bool:
        """Update a git repository."""
        try:
            valid_fields = [
                "name",
                "category",
                "url",
                "branch",
                "auth_type",
                "credential_name",
                "path",
                "verify_ssl",
                "git_author_name",
                "git_author_email",
                "description",
                "is_active",
            ]
            update_kwargs = {k: v for k, v in repo_data.items() if k in valid_fields}
            if not update_kwargs:
                return False

            if "name" in update_kwargs:
                existing = self._repo.get_by_name(update_kwargs["name"])
                if existing and existing.id != repo_id:
                    raise ValueError(
                        f"Repository with name '{update_kwargs['name']}' already exists"
                    )

            update_kwargs["updated_at"] = datetime.now(timezone.utc)
            self._repo.update(repo_id, **update_kwargs)
            logger.info("Updated git repository ID: %s", repo_id)
            return True
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error updating git repository %s: %s", repo_id, e)
            raise

    def delete_repository(self, repo_id: int, hard_delete: bool = True) -> bool:
        """Delete a git repository."""
        try:
            if hard_delete:
                self._repo.delete(repo_id)
                action = "Deleted"
            else:
                self._repo.update(
                    repo_id, is_active=False, updated_at=datetime.now(timezone.utc)
                )
                action = "Deactivated"
            logger.info("%s git repository ID: %s", action, repo_id)
            return True
        except Exception as e:
            logger.error("Error deleting git repository %s: %s", repo_id, e)
            raise

    def update_sync_status(
        self, repo_id: int, status: str, last_sync: Optional[datetime] = None
    ) -> bool:
        """Update the sync status of a repository."""
        try:
            if last_sync is None:
                last_sync = datetime.now(timezone.utc)
            self._repo.update(
                repo_id,
                sync_status=status,
                last_sync=last_sync,
                updated_at=datetime.now(timezone.utc),
            )
            return True
        except Exception as e:
            logger.error("Error updating sync status for repository %s: %s", repo_id, e)
            raise

    def health_check(self) -> Dict[str, Any]:
        """Check the health of the git repository management system."""
        try:
            all_repos = self._repo.get_all()
            active_repos = [r for r in all_repos if r.is_active]
            category_counts: Dict[str, int] = {}
            for repo in all_repos:
                category_counts[repo.category] = (
                    category_counts.get(repo.category, 0) + 1
                )
            return {
                "status": "healthy",
                "total_repositories": len(all_repos),
                "active_repositories": len(active_repos),
                "categories": category_counts,
                "database": "PostgreSQL",
            }
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return {"status": "error", "error": str(e), "database": "PostgreSQL"}

    def _to_dict(self, repo: GitRepository) -> Dict[str, Any]:
        """Convert GitRepository model to dictionary."""
        return {
            "id": repo.id,
            "name": repo.name,
            "category": repo.category,
            "url": repo.url,
            "branch": repo.branch,
            "auth_type": repo.auth_type,
            "credential_name": repo.credential_name,
            "path": repo.path,
            "verify_ssl": repo.verify_ssl,
            "git_author_name": repo.git_author_name,
            "git_author_email": repo.git_author_email,
            "description": repo.description,
            "is_active": repo.is_active,
            "last_sync": repo.last_sync.isoformat() if repo.last_sync else None,
            "sync_status": repo.sync_status,
            "created_at": repo.created_at.isoformat() if repo.created_at else None,
            "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
        }
