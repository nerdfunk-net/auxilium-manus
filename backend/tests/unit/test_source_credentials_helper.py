"""Tests for services.credentials.source_credentials (global-only resolution)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.credentials.exceptions import CredentialMissingFieldError
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)


class SourceCredentialsHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("services.credentials.source_credentials.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value
        self.db = MagicMock()

    def test_assert_global_returns_credential(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "u",
        }
        result = assert_global_credential(self.db, 3)
        self.assertEqual(result["id"], 3)

    def test_assert_global_rejects_missing(self) -> None:
        self.mock_service.get_credential_by_id.return_value = None
        with self.assertRaises(SourceCredentialError):
            assert_global_credential(self.db, 3)

    def test_assert_global_rejects_private(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {"id": 3, "visibility": "private"}
        with self.assertRaises(SourceCredentialError):
            assert_global_credential(self.db, 3)

    def test_resolve_secret_returns_username_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.return_value = "s3cr3t"
        username, password = resolve_global_secret(self.db, 3)
        self.assertEqual(username, "admin")
        self.assertEqual(password, "s3cr3t")

    def test_resolve_secret_rejects_credential_without_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.side_effect = CredentialMissingFieldError("none")
        with self.assertRaises(SourceCredentialError):
            resolve_global_secret(self.db, 3)


if __name__ == "__main__":
    unittest.main()
