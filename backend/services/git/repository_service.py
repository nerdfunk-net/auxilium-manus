"""Git repository CRUD service — manages git_repositories table in PostgreSQL.

Separate from GitService (git operations: clone, sync, pull).
This service only manages the database records.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

from core.config import settings
from core.crypto import EncryptionService
from core.models import GitRepository
from repositories import GitRepositoryRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class GitRepositoryService:
    """CRUD service for Git repositories in PostgreSQL.

    Separate from GitService (git operations: clone, sync, pull).
    This service only manages the database records.
    """

    def __init__(self, db: Session | None = None) -> None:
        self._db = db
        self._repo = GitRepositoryRepository(db)

    @cached_property
    def _encryption(self) -> EncryptionService:
        return EncryptionService(settings.credential_encryption_key or settings.secret_key)

    def create_repository(self, repo_data: dict[str, Any]) -> int:
        """Create a new git repository record. Returns new ID."""
        try:
            if self._repo.name_exists(repo_data["name"], db=self._db):
                raise ValueError(f"Repository with name '{repo_data['name']}' already exists")

            webhook_secret = repo_data.get("webhook_secret")
            new_repo = self._repo.create(
                db=self._db,
                name=repo_data["name"],
                category=repo_data["category"],
                url=repo_data["url"],
                branch=repo_data.get("branch", "main"),
                auth_type=repo_data.get("auth_type", "token"),
                credential_name=repo_data.get("credential_name"),
                path=repo_data.get("path"),
                verify_ssl=repo_data.get("verify_ssl", True),
                git_author_name=repo_data.get("git_author_name"),
                git_author_email=repo_data.get("git_author_email"),
                description=repo_data.get("description"),
                is_active=repo_data.get("is_active", True),
                webhook_secret_encrypted=(
                    self._encryption.encrypt(webhook_secret) if webhook_secret else None
                ),
                webhook_auto_deploy=bool(repo_data.get("webhook_auto_deploy", False)),
            )

            logger.info("Created git repository: %s (ID: %s)", repo_data["name"], new_repo.id)
            return new_repo.id
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error creating git repository: %s", e)
            raise

    def get_repository(self, repo_id: int) -> dict[str, Any] | None:
        """Get a git repository by ID."""
        try:
            repo = self._repo.get_by_id(repo_id, db=self._db)
            return self._to_dict(repo) if repo else None
        except Exception as e:
            logger.error("Error getting git repository %s: %s", repo_id, e)
            raise

    def get_repositories(
        self, category: str | None = None, active_only: bool = False
    ) -> list[dict[str, Any]]:
        """Get all git repositories, optionally filtered by category and active status."""
        try:
            if category:
                repos = self._repo.get_by_category(category, active_only, db=self._db)
            elif active_only:
                repos = self._repo.get_all_active(db=self._db)
            else:
                repos = self._repo.get_all(db=self._db)
            return [self._to_dict(r) for r in repos]
        except Exception as e:
            logger.error("Error getting git repositories: %s", e)
            raise

    def update_repository(self, repo_id: int, repo_data: dict[str, Any]) -> bool:
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
                "webhook_auto_deploy",
            ]
            update_kwargs = {k: v for k, v in repo_data.items() if k in valid_fields}
            # A non-empty webhook_secret is (re)encrypted; an explicit empty
            # string clears it; omitting the key leaves the stored secret.
            if "webhook_secret" in repo_data:
                secret = repo_data.get("webhook_secret")
                update_kwargs["webhook_secret_encrypted"] = (
                    self._encryption.encrypt(secret) if secret else None
                )
            if not update_kwargs:
                return False

            if "name" in update_kwargs:
                existing = self._repo.get_by_name(update_kwargs["name"], db=self._db)
                if existing and existing.id != repo_id:
                    raise ValueError(
                        f"Repository with name '{update_kwargs['name']}' already exists"
                    )

            update_kwargs["updated_at"] = datetime.now(UTC)
            self._repo.update(repo_id, db=self._db, **update_kwargs)
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
                self._repo.delete(repo_id, db=self._db)
                action = "Deleted"
            else:
                self._repo.update(
                    repo_id, db=self._db, is_active=False, updated_at=datetime.now(UTC)
                )
                action = "Deactivated"
            logger.info("%s git repository ID: %s", action, repo_id)
            return True
        except Exception as e:
            logger.error("Error deleting git repository %s: %s", repo_id, e)
            raise

    def update_sync_status(
        self, repo_id: int, status: str, last_sync: datetime | None = None
    ) -> bool:
        """Update the sync status of a repository."""
        try:
            if last_sync is None:
                last_sync = datetime.now(UTC)
            self._repo.update(
                repo_id,
                db=self._db,
                sync_status=status,
                last_sync=last_sync,
                updated_at=datetime.now(UTC),
            )
            return True
        except Exception as e:
            logger.error("Error updating sync status for repository %s: %s", repo_id, e)
            raise

    def health_check(self) -> dict[str, Any]:
        """Check the health of the git repository management system."""
        try:
            all_repos = self._repo.get_all(db=self._db)
            active_repos = [r for r in all_repos if r.is_active]
            category_counts: dict[str, int] = {}
            for repo in all_repos:
                category_counts[repo.category] = category_counts.get(repo.category, 0) + 1
            return {
                "status": "healthy",
                "total_repositories": len(all_repos),
                "active_repositories": len(active_repos),
                "categories": category_counts,
                "database": "PostgreSQL",
            }
        except Exception:
            logger.exception("Health check failed")
            return {"status": "error", "error": "unavailable", "database": "PostgreSQL"}

    def get_webhook_secret(self, repo_id: int) -> str | None:
        """Decrypt and return a repository's webhook secret. Only the webhook
        router should call this — ``_to_dict`` / ``load_git_repository`` never
        expose it.
        """
        repo = self._repo.get_by_id(repo_id, db=self._db)
        if repo is None or not repo.webhook_secret_encrypted:
            return None
        return self._encryption.decrypt(repo.webhook_secret_encrypted)

    def _to_dict(self, repo: GitRepository) -> dict[str, Any]:
        """Convert GitRepository model to dictionary.

        The webhook secret is deliberately omitted; only its presence is
        exposed via ``has_webhook_secret``.
        """
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
            "has_webhook_secret": repo.webhook_secret_encrypted is not None,
            "webhook_auto_deploy": bool(repo.webhook_auto_deploy),
            "created_at": repo.created_at.isoformat() if repo.created_at else None,
            "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
        }
