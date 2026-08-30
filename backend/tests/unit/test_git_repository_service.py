"""CRUD tests for services/git/repository_service.py against in-memory SQLite."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import GitRepository
from services.git.repository_service import GitRepositoryService

_BASE = {
    "name": "configs",
    "category": "device_configs",
    "url": "https://example.com/configs.git",
}


class GitRepositoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        GitRepository.metadata.create_all(engine, tables=[GitRepository.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = GitRepositoryService(self.db)

    def _create(self, **overrides) -> int:
        return self.service.create_repository({**_BASE, **overrides})

    def test_create_applies_defaults(self) -> None:
        repo_id = self._create()
        stored = self.service.get_repository(repo_id)
        self.assertEqual(stored["branch"], "main")
        self.assertEqual(stored["auth_type"], "token")
        self.assertTrue(stored["verify_ssl"])
        self.assertTrue(stored["is_active"])

    def test_create_rejects_duplicate_name(self) -> None:
        self._create()
        with self.assertRaises(ValueError):
            self._create()

    def test_get_repository_missing_returns_none(self) -> None:
        self.assertIsNone(self.service.get_repository(999))

    def test_get_repositories_filters(self) -> None:
        self._create(name="a", category="device_configs")
        self._create(name="b", category="templates")
        self._create(name="c", category="templates", is_active=False)

        self.assertEqual(len(self.service.get_repositories()), 3)
        self.assertEqual(len(self.service.get_repositories(category="templates")), 2)
        self.assertEqual(
            len(self.service.get_repositories(category="templates", active_only=True)), 1
        )
        self.assertEqual(len(self.service.get_repositories(active_only=True)), 2)

    def test_update_repository_changes_fields(self) -> None:
        repo_id = self._create()
        self.assertTrue(self.service.update_repository(repo_id, {"branch": "develop"}))
        self.assertEqual(self.service.get_repository(repo_id)["branch"], "develop")

    def test_update_repository_ignores_unknown_fields(self) -> None:
        repo_id = self._create()
        self.assertFalse(self.service.update_repository(repo_id, {"bogus": "x"}))

    def test_update_repository_rename_collision_raises(self) -> None:
        first = self._create(name="first")
        self._create(name="second")
        with self.assertRaises(ValueError):
            self.service.update_repository(first, {"name": "second"})

    def test_update_repository_rename_to_same_name_ok(self) -> None:
        repo_id = self._create(name="first")
        self.assertTrue(self.service.update_repository(repo_id, {"name": "first", "branch": "x"}))

    def test_hard_delete_removes_row(self) -> None:
        repo_id = self._create()
        self.assertTrue(self.service.delete_repository(repo_id))
        self.assertIsNone(self.service.get_repository(repo_id))

    def test_soft_delete_deactivates(self) -> None:
        repo_id = self._create()
        self.assertTrue(self.service.delete_repository(repo_id, hard_delete=False))
        self.assertFalse(self.service.get_repository(repo_id)["is_active"])

    def test_update_sync_status_sets_status_and_timestamp(self) -> None:
        repo_id = self._create()
        pinned = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertTrue(self.service.update_sync_status(repo_id, "success", last_sync=pinned))
        stored = self.service.get_repository(repo_id)
        self.assertEqual(stored["sync_status"], "success")
        self.assertIsNotNone(stored["last_sync"])

    def test_update_sync_status_defaults_timestamp(self) -> None:
        repo_id = self._create()
        self.service.update_sync_status(repo_id, "syncing")
        self.assertIsNotNone(self.service.get_repository(repo_id)["last_sync"])

    def test_health_check_reports_counts(self) -> None:
        self._create(name="a", category="device_configs")
        self._create(name="b", category="templates", is_active=False)
        health = self.service.health_check()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["total_repositories"], 2)
        self.assertEqual(health["active_repositories"], 1)
        self.assertEqual(health["categories"], {"device_configs": 1, "templates": 1})

    def test_health_check_error_path(self) -> None:
        self.service._repo = MagicMock()
        self.service._repo.get_all.side_effect = RuntimeError("db down")
        health = self.service.health_check()
        self.assertEqual(health["status"], "error")

    def test_to_dict_serialises_timestamps(self) -> None:
        repo_id = self._create()
        stored = self.service.get_repository(repo_id)
        self.assertIsNone(stored["last_sync"])
        self.assertIsInstance(stored["created_at"], str)


if __name__ == "__main__":
    unittest.main()
