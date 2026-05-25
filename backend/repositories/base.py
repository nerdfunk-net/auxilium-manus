"""Base repository with common CRUD operations."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Generic, List, Optional, Type, TypeVar

from sqlalchemy.orm import Session

from core.database import get_db_session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, model: Type[T]):
        self.model = model

    @contextmanager
    def _db_session(
        self, db: Optional[Session] = None
    ) -> Generator[Session, None, None]:
        if db is not None:
            yield db
        else:
            session = get_db_session()
            try:
                yield session
            finally:
                session.close()

    def get_by_id(self, id: int, db: Optional[Session] = None) -> Optional[T]:
        with self._db_session(db) as s:
            return s.query(self.model).filter(self.model.id == id).first()

    def get_all(self, db: Optional[Session] = None) -> List[T]:
        with self._db_session(db) as s:
            return s.query(self.model).all()

    def create(self, db: Optional[Session] = None, **kwargs) -> T:
        if db is not None:
            obj = self.model(**kwargs)
            db.add(obj)
            db.flush()
            db.refresh(obj)
            return obj

        with self._db_session() as s:
            obj = self.model(**kwargs)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def update(self, id: int, db: Optional[Session] = None, **kwargs) -> Optional[T]:
        if db is not None:
            obj = db.query(self.model).filter(self.model.id == id).first()
            if obj:
                for key, value in kwargs.items():
                    if hasattr(obj, key):
                        setattr(obj, key, value)
                db.flush()
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

    def delete(self, id: int, db: Optional[Session] = None) -> bool:
        if db is not None:
            obj = db.query(self.model).filter(self.model.id == id).first()
            if obj:
                db.delete(obj)
                db.flush()
                return True
            return False

        with self._db_session() as s:
            obj = s.query(self.model).filter(self.model.id == id).first()
            if obj:
                s.delete(obj)
                s.commit()
                return True
            return False

    def filter(self, db: Optional[Session] = None, **kwargs) -> List[T]:
        with self._db_session(db) as s:
            query = s.query(self.model)
            for key, value in kwargs.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
            return query.all()

    def count(self, db: Optional[Session] = None) -> int:
        with self._db_session(db) as s:
            return s.query(self.model).count()

    def exists(self, id: int, db: Optional[Session] = None) -> bool:
        with self._db_session(db) as s:
            return s.query(self.model).filter(self.model.id == id).count() > 0
