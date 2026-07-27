"""Tests for encrypted credential storage and visibility scoping."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

from core.crypto import EncryptionService
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNameConflictError,
    CredentialNotFoundError,
)


def _make_credential(**overrides) -> MagicMock:
    credential = MagicMock()
    credential.id = overrides.get("id", 1)
    credential.name = overrides.get("name", "lab-router")
    credential.username = overrides.get("username", "admin")
    credential.type = overrides.get("type", "ssh")
    credential.valid_until = overrides.get("valid_until", None)
    credential.is_active = overrides.get("is_active", True)
    credential.source = overrides.get("source", "general")
    credential.owner = overrides.get("owner", None)
    credential.owner_user_id = overrides.get("owner_user_id", None)
    credential.visibility = overrides.get("visibility", "global")
    credential.created_at = overrides.get("created_at", None)
    credential.updated_at = overrides.get("updated_at", None)
    credential.password_encrypted = overrides.get("password_encrypted", b"encrypted")
    credential.ssh_key_encrypted = overrides.get("ssh_key_encrypted", None)
    credential.ssh_passphrase_encrypted = overrides.get("ssh_passphrase_encrypted", None)
    return credential


class CredentialsServiceTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        service = EncryptionService("test-secret-key-for-credentials")
        encrypted = service.encrypt("super-secret")
        self.assertEqual(service.decrypt(encrypted), "super-secret")

    def test_to_dict_marks_expiring_status(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        credential = _make_credential(valid_until=(date.today() + timedelta(days=3)).isoformat())

        result = cred_service._to_dict(credential)
        self.assertEqual(result["status"], "expiring")
        self.assertTrue(result["has_password"])

    def test_to_dict_includes_visibility_and_owner_fields(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        credential = _make_credential(visibility="private", owner_user_id=7)

        result = cred_service._to_dict(credential, owner_username="alice")
        self.assertEqual(result["visibility"], "private")
        self.assertEqual(result["owner_user_id"], 7)
        self.assertEqual(result["owner_username"], "alice")

    def test_list_credentials_returns_global_and_own_private_only(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        global_cred = _make_credential(id=1, name="shared", visibility="global")
        own_private = _make_credential(id=2, name="mine", visibility="private", owner_user_id=42)
        cred_service._repo.list_visible.return_value = [
            (global_cred, None),
            (own_private, "alice"),
        ]

        result = cred_service.list_credentials(source="general", acting_user_id=42)

        cred_service._repo.list_visible.assert_called_once_with(acting_user_id=42, source="general")
        names = {item["name"] for item in result}
        self.assertEqual(names, {"shared", "mine"})

    def test_create_credential_defaults_to_private_and_sets_owner(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        cred_service._repo.find_private_conflict.return_value = None
        created = _make_credential(visibility="private", owner_user_id=5)
        cred_service._repo.create.return_value = created

        cred_service.create_credential(
            name="my-cred",
            username="admin",
            cred_type="ssh",
            password="secret",
            acting_user_id=5,
        )

        cred_service._repo.find_private_conflict.assert_called_once_with("my-cred", "general", 5)
        _, kwargs = cred_service._repo.create.call_args
        self.assertEqual(kwargs["visibility"], "private")
        self.assertEqual(kwargs["owner_user_id"], 5)

    def test_create_private_credential_without_acting_user_raises(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()

        with self.assertRaises(CredentialMissingFieldError):
            cred_service.create_credential(
                name="my-cred",
                username="admin",
                cred_type="ssh",
                password="secret",
                visibility="private",
                acting_user_id=None,
            )

    def test_create_global_credential_checks_global_conflict_only(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        cred_service._repo.find_global_conflict.return_value = None
        created = _make_credential(visibility="global", owner_user_id=None)
        cred_service._repo.create.return_value = created

        cred_service.create_credential(
            name="shared-cred",
            username="admin",
            cred_type="ssh",
            password="secret",
            visibility="global",
            acting_user_id=5,
        )

        cred_service._repo.find_global_conflict.assert_called_once_with("shared-cred", "general")
        cred_service._repo.find_private_conflict.assert_not_called()
        _, kwargs = cred_service._repo.create.call_args
        self.assertIsNone(kwargs["owner_user_id"])

    def test_two_users_can_create_private_credentials_with_same_name(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        # From user 5's perspective, user 9's identically-named private
        # credential is invisible, so no conflict is found.
        cred_service._repo.find_private_conflict.return_value = None
        created = _make_credential(visibility="private", owner_user_id=9)
        cred_service._repo.create.return_value = created

        cred_service.create_credential(
            name="prod-admin",
            username="admin",
            cred_type="ssh",
            password="secret",
            acting_user_id=9,
        )

        cred_service._repo.find_private_conflict.assert_called_once_with("prod-admin", "general", 9)

    def test_cross_owner_global_name_conflict_raises(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        cred_service._repo.find_global_conflict.return_value = _make_credential(id=99)

        with self.assertRaises(CredentialNameConflictError):
            cred_service.create_credential(
                name="shared-cred",
                username="admin",
                cred_type="ssh",
                password="secret",
                visibility="global",
                acting_user_id=5,
            )

    def test_get_credential_by_id_raises_not_found_for_other_users_private(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        # get_by_id_for_user itself enforces ownership; simulate its contract
        # by returning None when the acting user doesn't own the credential.
        cred_service._repo.get_by_id_for_user.return_value = None

        result = cred_service.get_credential_by_id(123, acting_user_id=99)

        self.assertIsNone(result)
        cred_service._repo.get_by_id_for_user.assert_called_once_with(123, acting_user_id=99)

    def test_get_decrypted_password_scoped_to_owner(self) -> None:
        db = MagicMock()
        cred_service = CredentialsService(db)
        cred_service._repo = MagicMock()
        cred_service._repo.get_by_id_for_user.return_value = None

        with self.assertRaises(CredentialNotFoundError):
            cred_service.get_decrypted_password(123, acting_user_id=99)


if __name__ == "__main__":
    unittest.main()
