"""Repository for git repository operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import GitRepository
from repositories.base import BaseRepository


class GitRepositoryRepository(BaseRepository[GitRepository]):
    """Repository for managing git repositories."""

    # Exactly the keys GitRepositoryService passes to ``update`` (Q6/Q8).
    updatable_fields = frozenset(
        {
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
            "webhook_secret_encrypted",
            "sync_status",
            "last_sync",
            "updated_at",
        }
    )

    def __init__(self, db: Session | None = None):
        super().__init__(GitRepository)
        self._db = db

    def get_by_name(self, name: str, db: Session | None = None) -> GitRepository | None:
        with self._db_session(db or self._db) as s:
            return s.scalar(select(GitRepository).where(GitRepository.name == name))

    def get_by_category(
        self, category: str, active_only: bool = True, db: Session | None = None
    ) -> list[GitRepository]:
        with self._db_session(db or self._db) as s:
            stmt = select(GitRepository).where(GitRepository.category == category)
            if active_only:
                stmt = stmt.where(GitRepository.is_active)
            return list(s.scalars(stmt))

    def get_all_active(self, db: Session | None = None) -> list[GitRepository]:
        with self._db_session(db or self._db) as s:
            return list(s.scalars(select(GitRepository).where(GitRepository.is_active)))

    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db or self._db) as s:
            count = s.scalar(
                select(func.count()).select_from(GitRepository).where(GitRepository.name == name)
            )
            return (count or 0) > 0
