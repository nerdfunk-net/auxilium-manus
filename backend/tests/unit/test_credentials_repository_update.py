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
