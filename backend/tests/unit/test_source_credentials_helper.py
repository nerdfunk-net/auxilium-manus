"""Tests for services.credentials.source_credentials (global-only resolution)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.credentials.exceptions import CredentialMissingFieldError
from services.credentials.source_credentials import (
    SOURCE_CREDENTIAL_TYPES,
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)


class SourceCredentialsHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("services.credentials.manager.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value
        self.db = MagicMock()

    def test_assert_global_returns_credential(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "type": "generic",
            "username": "u",
        }
        result = assert_global_credential(self.db, 3, source_type="ise")
        self.assertEqual(result["id"], 3)

    def test_assert_global_rejects_missing(self) -> None:
        self.mock_service.get_credential_by_id.return_value = None
        with self.assertRaises(SourceCredentialError):
            assert_global_credential(self.db, 3, source_type="ise")

    def test_assert_global_rejects_private(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {"id": 3, "visibility": "private"}
        with self.assertRaises(SourceCredentialError):
            assert_global_credential(self.db, 3, source_type="ise")

    def test_resolve_secret_returns_username_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "type": "generic",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.return_value = "s3cr3t"
        username, password = resolve_global_secret(self.db, 3, source_type="ise")
        self.assertEqual(username, "admin")
        self.assertEqual(password, "s3cr3t")

    def test_resolve_secret_rejects_credential_without_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "type": "generic",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.side_effect = CredentialMissingFieldError("none")
        with self.assertRaises(SourceCredentialError):
            resolve_global_secret(self.db, 3, source_type="ise")


if __name__ == "__main__":
    unittest.main()


class SourceCredentialTypeTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("services.credentials.manager.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value
        self.db = MagicMock()

    def _credential(self, cred_type: str) -> dict:
        return {"id": 3, "visibility": "global", "type": cred_type, "username": "u"}

    def test_assert_global_rejects_wrong_type(self) -> None:
        self.mock_service.get_credential_by_id.return_value = self._credential("ssh")
        with self.assertRaisesRegex(SourceCredentialError, "generic"):
            assert_global_credential(self.db, 3, source_type="ise")

    def test_token_source_accepts_token_and_rejects_generic(self) -> None:
        self.mock_service.get_credential_by_id.return_value = self._credential("token")
        self.assertEqual(assert_global_credential(self.db, 3, source_type="nautobot")["id"], 3)
        self.mock_service.get_credential_by_id.return_value = self._credential("generic")
        with self.assertRaisesRegex(SourceCredentialError, "token"):
            assert_global_credential(self.db, 3, source_type="nautobot")

    def test_resolve_secret_rejects_wrong_type(self) -> None:
        self.mock_service.get_credential_by_id.return_value = self._credential("ssh")
        self.mock_service.get_decrypted_password.return_value = "s3cr3t"
        with self.assertRaises(SourceCredentialError):
            resolve_global_secret(self.db, 3, source_type="catalyst_center")
        self.mock_service.get_decrypted_password.assert_not_called()

    def test_every_source_type_has_a_credential_type_rule(self) -> None:
        self.assertEqual(
            set(SOURCE_CREDENTIAL_TYPES),
            {"nautobot", "mattermost", "pyats", "ise", "catalyst_center"},
        )
