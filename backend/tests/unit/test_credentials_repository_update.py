"""CredentialsRepository.update only writes whitelisted attributes (Q6)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from repositories.credentials_repository import CredentialsRepository


class CredentialsRepositoryUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.repo = CredentialsRepository(self.db)
        self.credential = MagicMock()

    def test_allowed_fields_are_written_and_committed(self) -> None:
        self.repo.update(self.credential, name="renamed", visibility="global")
        self.assertEqual(self.credential.name, "renamed")
        self.assertEqual(self.credential.visibility, "global")
        self.db.commit.assert_called_once()

    def test_unknown_or_dangerous_attribute_is_refused_before_commit(self) -> None:
        for bad in ({"id": 99}, {"storage_backend": "vault"}, {"created_at": None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.repo.update(self.credential, **bad)
        self.db.commit.assert_not_called()


class OrphanedPrivateCredentialTests(unittest.TestCase):
    def test_private_credential_without_owner_is_invisible_to_system_context(self) -> None:
        db = MagicMock()
        repo = CredentialsRepository(db)
        orphan = MagicMock(visibility="private", owner_user_id=None)
        db.scalar.return_value = orphan
        # acting_user_id=None is how system contexts (git, schedules) resolve credentials
        self.assertIsNone(repo.get_by_id_for_user(1, acting_user_id=None))

    def test_global_and_owned_private_credentials_stay_visible(self) -> None:
        db = MagicMock()
        repo = CredentialsRepository(db)
        db.scalar.return_value = MagicMock(visibility="global", owner_user_id=None)
        self.assertIsNotNone(repo.get_by_id_for_user(1, acting_user_id=None))
        db.scalar.return_value = MagicMock(visibility="private", owner_user_id=4)
        self.assertIsNotNone(repo.get_by_id_for_user(1, acting_user_id=4))
        self.assertIsNone(repo.get_by_id_for_user(1, acting_user_id=5))


class ListVisibleOrphanTests(unittest.TestCase):
    def test_list_visible_requires_an_owner_for_private_rows(self) -> None:
        """acting_user_id=None must not match ``owner_user_id IS NULL`` (S3-07)."""
        from sqlalchemy.dialects import postgresql

        db = MagicMock()
        db.execute.return_value.all.return_value = []
        CredentialsRepository(db).list_visible(acting_user_id=None, source=None)
        stmt = db.execute.call_args.args[0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        self.assertIn("credentials.owner_user_id IS NOT NULL", sql)
