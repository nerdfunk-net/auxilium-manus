"""Query-side coverage for repositories/base.py (get_all / filter / count / exists
and the ``db is None`` fallback that borrows a session from get_db_session)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.git import GitRepository
from repositories.base import BaseRepository


def _repo_kwargs(name: str) -> dict:
    return {
        "name": name,
        "category": "workflows",
        "url": "https://example.com/r.git",
        "branch": "main",
    }


class BaseRepositoryQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[GitRepository.__table__])
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.repo = BaseRepository(GitRepository)
        for n in ("a", "b", "c"):
            self.repo.create(db=self.db, **_repo_kwargs(n))

    def test_get_all(self) -> None:
        rows = self.repo.get_all(db=self.db)
        self.assertEqual({r.name for r in rows}, {"a", "b", "c"})

    def test_filter_matches_and_ignores_unknown_keys(self) -> None:
        rows = self.repo.filter(db=self.db, name="b", not_a_column="x")
        self.assertEqual([r.name for r in rows], ["b"])

    def test_count(self) -> None:
        self.assertEqual(self.repo.count(db=self.db), 3)

    def test_exists(self) -> None:
        row = self.repo.filter(db=self.db, name="a")[0]
        self.assertTrue(self.repo.exists(row.id, db=self.db))
        self.assertFalse(self.repo.exists(999_999, db=self.db))

    def test_update_and_delete_missing_id_are_noops(self) -> None:
        self.assertIsNone(self.repo.update(999_999, db=self.db, name="x"))
        self.assertFalse(self.repo.delete(999_999, db=self.db))

    def test_db_none_borrows_and_closes_a_session(self) -> None:
        borrowed = self.Session()
        closed = {"value": False}
        real_close = borrowed.close

        def _tracking_close() -> None:
            closed["value"] = True
            real_close()

        borrowed.close = _tracking_close  # type: ignore[method-assign]

        # BaseRepository._db_session(None) -> get_db_session(); wrap it so we can
        # assert the borrowed session is closed in the finally block.
        with patch("repositories.base.get_db_session", return_value=borrowed):
            rows = self.repo.get_all()
        self.assertEqual(len(rows), 3)
        self.assertTrue(closed["value"])


if __name__ == "__main__":
    unittest.main()
