"""BaseRepository.update only touches whitelisted attributes (Q6/Q8)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.git import GitRepository
from repositories.base import BaseRepository
from repositories.git.git_repository_repository import GitRepositoryRepository


class BaseRepositoryUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[GitRepository.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.repo = GitRepositoryRepository()
        self.row = self.repo.create(
            db=self.db, name="a", category="workflows", url="https://x/r.git", branch="main"
        )

    def test_allowed_field_is_updated(self) -> None:
        updated = self.repo.update(self.row.id, db=self.db, branch="dev")
        self.assertEqual(updated.branch, "dev")

    def test_disallowed_field_raises_and_changes_nothing(self) -> None:
        with self.assertRaisesRegex(ValueError, "created_at"):
            self.repo.update(self.row.id, db=self.db, branch="dev", created_at=None)
        self.db.rollback()
        self.assertEqual(self.repo.get_by_id(self.row.id, db=self.db).branch, "main")

    def test_subclass_without_allow_list_can_update_nothing(self) -> None:
        plain = BaseRepository(GitRepository)
        with self.assertRaises(ValueError):
            plain.update(self.row.id, db=self.db, branch="x")
        self.db.rollback()
        self.assertEqual(self.repo.get_by_id(self.row.id, db=self.db).branch, "main")

    def test_exact_name_lookup_and_exists(self) -> None:
        self.assertEqual(self.repo.get_by_name("a", db=self.db).id, self.row.id)
        self.assertTrue(self.repo.name_exists("a", db=self.db))
        self.assertFalse(self.repo.name_exists("zzz", db=self.db))
