"""Tests for encrypted credential storage."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

from core.crypto import EncryptionService
from services.credentials.credentials_service import CredentialsService


class CredentialsServiceTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        service = EncryptionService("test-secret-key-for-credentials")
        encrypted = service.encrypt("super-secret")
        self.assertEqual(service.decrypt(encrypted), "super-secret")

    def test_to_dict_marks_expiring_status(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        credential = MagicMock()
        credential.id = 1
        credential.name = "lab-router"
        credential.username = "admin"
        credential.type = "ssh"
        credential.valid_until = (date.today() + timedelta(days=3)).isoformat()
        credential.is_active = True
        credential.source = "general"
        credential.owner = None
        credential.created_at = None
        credential.updated_at = None
        credential.password_encrypted = b"encrypted"
        credential.ssh_key_encrypted = None
        credential.ssh_passphrase_encrypted = None

        result = cred_service._to_dict(credential)
        self.assertEqual(result["status"], "expiring")
        self.assertTrue(result["has_password"])


if __name__ == "__main__":
    unittest.main()
