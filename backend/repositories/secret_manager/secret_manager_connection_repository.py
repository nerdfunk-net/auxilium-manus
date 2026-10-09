"""Repository for secret manager connection operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import SecretManagerConnection
from repositories.base import BaseRepository


class SecretManagerConnectionRepository(BaseRepository[SecretManagerConnection]):
    """Repository for managing secret manager connections."""

    # Exactly the keys SecretManagerConnectionService.update_connection passes (Q6/Q8).
    updatable_fields = frozenset(
        {
            "name",
            "backend",
            "credential_name",
            "verify_ssl",
            "is_active",
            "backend_config",
            "description",
            "updated_at",
        }
    )

    def __init__(self, db: Session | None = None):
        super().__init__(SecretManagerConnection)
        self._db = db

    def get_by_name(
        self, name: str, db: Session | None = None
    ) -> SecretManagerConnection | None:
        with self._db_session(db or self._db) as s:
            return s.scalar(
                select(SecretManagerConnection).where(SecretManagerConnection.name == name)
            )

    def get_all_active(self, db: Session | None = None) -> list[SecretManagerConnection]:
        with self._db_session(db or self._db) as s:
            return list(
                s.scalars(select(SecretManagerConnection).where(SecretManagerConnection.is_active))
            )

    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db or self._db) as s:
            count = s.scalar(
                select(func.count())
                .select_from(SecretManagerConnection)
                .where(SecretManagerConnection.name == name)
            )
            return (count or 0) > 0

    def get_by_id_fresh(
        self, connection_id: int, db: Session | None = None
    ) -> SecretManagerConnection | None:
        """PK lookup that always hits the database and overwrites the identity
        map (``populate_existing``). A worker session that already loaded this
        row must still see commits from the API process (SM4)."""
        with self._db_session(db or self._db) as s:
            return s.scalar(
                select(SecretManagerConnection)
                .where(SecretManagerConnection.id == connection_id)
                .execution_options(populate_existing=True)
            )
