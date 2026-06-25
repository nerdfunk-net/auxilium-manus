"""Repository for git repository operations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.models import GitRepository
from repositories.base import BaseRepository


class GitRepositoryRepository(BaseRepository[GitRepository]):
    """Repository for managing git repositories."""

    def __init__(self):
        super().__init__(GitRepository)

    def get_by_name(self, name: str, db: Session | None = None) -> GitRepository | None:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.name == name).first()

    def get_by_category(
        self, category: str, active_only: bool = True, db: Session | None = None
    ) -> list[GitRepository]:
        with self._db_session(db) as s:
            query = s.query(GitRepository).filter(GitRepository.category == category)
            if active_only:
                query = query.filter(GitRepository.is_active)
            return query.all()

    def get_all_active(self, db: Session | None = None) -> list[GitRepository]:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.is_active).all()

    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.name == name).count() > 0
