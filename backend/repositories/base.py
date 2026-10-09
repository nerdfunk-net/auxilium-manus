"""Base repository with common CRUD operations."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_db_session
from repositories.updates import apply_updates


class BaseRepository[T]:
    """Base repository with common CRUD operations."""

    # Attribute names ``update`` may set. Empty by default: a subclass that forgets its
    # allow-list can update nothing rather than every column (including the primary key).
    updatable_fields: frozenset[str] = frozenset()

    def __init__(self, model: type[T]):
        self.model = model

    @contextmanager
    def _db_session(self, db: Session | None = None) -> Generator[Session]:
        if db is not None:
            yield db
        else:
            session = get_db_session()
            try:
                yield session
            finally:
                session.close()

    def get_by_id(self, id: int, db: Session | None = None) -> T | None:
        with self._db_session(db) as s:
            return s.get(self.model, id)

    def get_all(self, db: Session | None = None) -> list[T]:
        with self._db_session(db) as s:
            return list(s.scalars(select(self.model)))

    def create(self, db: Session | None = None, **kwargs) -> T:
        # _db_session yields the caller's session as-is (not closed) or opens/closes one.
        with self._db_session(db) as s:
            obj = self.model(**kwargs)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def update(self, id: int, db: Session | None = None, **kwargs) -> T | None:
        with self._db_session(db) as s:
            obj = s.get(self.model, id)
            if obj is not None:
                apply_updates(obj, kwargs, self.updatable_fields)
                s.commit()
                s.refresh(obj)
            return obj

    def delete(self, id: int, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            obj = s.get(self.model, id)
            if obj is None:
                return False
            s.delete(obj)
            s.commit()
            return True

    def filter(self, db: Session | None = None, **kwargs) -> list[T]:
        with self._db_session(db) as s:
            stmt = select(self.model)
            for key, value in kwargs.items():
                if hasattr(self.model, key):
                    stmt = stmt.where(getattr(self.model, key) == value)
            return list(s.scalars(stmt))

    def count(self, db: Session | None = None) -> int:
        with self._db_session(db) as s:
            return s.scalar(select(func.count()).select_from(self.model)) or 0

    def exists(self, id: int, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            return s.get(self.model, id) is not None
