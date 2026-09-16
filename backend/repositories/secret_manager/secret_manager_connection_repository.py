"""Repository for secret manager connection operations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.models import SecretManagerConnection
from repositories.base import BaseRepository


class SecretManagerConnectionRepository(BaseRepository[SecretManagerConnection]):
    """Repository for managing secret manager connections."""

    def __init__(self, db: Session | None = None):
        super().__init__(SecretManagerConnection)
        self._db = db

    def get_by_name(
        self, name: str, db: Session | None = None
    ) -> SecretManagerConnection | None:
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.name == name)
                .first()
            )

    def get_all_active(self, db: Session | None = None) -> list[SecretManagerConnection]:
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.is_active)
                .all()
            )

    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.name == name)
                .count()
                > 0
            )
