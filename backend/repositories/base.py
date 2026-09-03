"""Base repository with common CRUD operations."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from core.database import get_db_session


class BaseRepository[T]:
    """Base repository with common CRUD operations."""

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
            return s.query(self.model).filter(self.model.id == id).first()

    def get_all(self, db: Session | None = None) -> list[T]:
        with self._db_session(db) as s:
            return s.query(self.model).all()

    def create(self, db: Session | None = None, **kwargs) -> T:
        if db is not None:
            obj = self.model(**kwargs)
            db.add(obj)
            db.commit()
            db.refresh(obj)
            return obj

        with self._db_session() as s:
            obj = self.model(**kwargs)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def update(self, id: int, db: Session | None = None, **kwargs) -> T | None:
        if db is not None:
            obj = db.query(self.model).filter(self.model.id == id).first()
            if obj:
                for key, value in kwargs.items():
                    if hasattr(obj, key):
                        setattr(obj, key, value)
                db.commit()
                db.refresh(obj)
            return obj

        with self._db_session() as s:
            obj = s.query(self.model).filter(self.model.id == id).first()
            if obj:
                for key, value in kwargs.items():
                    if hasattr(obj, key):
                        setattr(obj, key, value)
                s.commit()
                s.refresh(obj)
            return obj

    def delete(self, id: int, db: Session | None = None) -> bool:
        if db is not None:
            obj = db.query(self.model).filter(self.model.id == id).first()
            if obj:
                db.delete(obj)
                db.commit()
                return True
            return False

        with self._db_session() as s:
            obj = s.query(self.model).filter(self.model.id == id).first()
            if obj:
                s.delete(obj)
                s.commit()
                return True
            return False

    def filter(self, db: Session | None = None, **kwargs) -> list[T]:
        with self._db_session(db) as s:
            query = s.query(self.model)
            for key, value in kwargs.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
            return query.all()

    def count(self, db: Session | None = None) -> int:
        with self._db_session(db) as s:
            return s.query(self.model).count()

    def exists(self, id: int, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            return s.query(self.model).filter(self.model.id == id).count() > 0
