"""Repository for git repository operations."""

from typing import List, Optional

from core.database import get_db_session
from core.models import GitRepository
from repositories.base import BaseRepository


class GitRepositoryRepository(BaseRepository[GitRepository]):
    """Repository for managing git repositories."""

    def __init__(self):
        super().__init__(GitRepository)

    def get_by_name(self, name: str) -> Optional[GitRepository]:
        """Get git repository by name.

        Args:
            name: Repository name

        Returns:
            GitRepository if found, None otherwise
        """
        db = get_db_session()
        try:
            return db.query(GitRepository).filter(GitRepository.name == name).first()
        finally:
            db.close()

    def get_by_category(
        self, category: str, active_only: bool = True
    ) -> List[GitRepository]:
        """Get repositories by category.

        Args:
            category: Category to filter by
            active_only: If True, only return active repositories

        Returns:
            List of git repositories
        """
        db = get_db_session()
        try:
            query = db.query(GitRepository).filter(GitRepository.category == category)
            if active_only:
                query = query.filter(GitRepository.is_active)
            return query.all()
        finally:
            db.close()

    def get_all_active(self) -> List[GitRepository]:
        """Get all active repositories.

        Returns:
            List of active git repositories
        """
        db = get_db_session()
        try:
            return db.query(GitRepository).filter(GitRepository.is_active).all()
        finally:
            db.close()

    def name_exists(self, name: str) -> bool:
        """Check if repository name exists.

        Args:
            name: Repository name to check

        Returns:
            True if name exists, False otherwise
        """
        db = get_db_session()
        try:
            return (
                db.query(GitRepository).filter(GitRepository.name == name).count() > 0
            )
        finally:
            db.close()
