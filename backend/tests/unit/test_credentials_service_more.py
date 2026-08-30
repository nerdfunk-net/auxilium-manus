"""Additional coverage for services/credentials/credentials_service.py:

update / delete / decrypt / SSH-key export paths not covered by
test_credentials_service.py.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNameConflictError,
    CredentialNotFoundError,
)


def _credential(**over) -> MagicMock:
    c = MagicMock()
    c.id = over.get("id", 1)
    c.name = over.get("name", "lab-router")
    c.username = over.get("username", "admin")
    c.type = over.get("type", "ssh")
    c.valid_until = over.get("valid_until", None)
    c.is_active = over.get("is_active", True)
    c.source = over.get("source", "general")
    c.owner = over.get("owner", None)
    c.owner_user_id = over.get("owner_user_id", None)
    c.visibility = over.get("visibility", "global")
    c.created_at = over.get("created_at", None)
    c.updated_at = over.get("updated_at", None)
    c.password_encrypted = over.get("password_encrypted", None)
    c.ssh_key_encrypted = over.get("ssh_key_encrypted", None)
    c.ssh_passphrase_encrypted = over.get("ssh_passphrase_encrypted", None)
    return c


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        data_dir = Path(self._tmp.name)
        p = patch(
            "services.credentials.credentials_service.settings.data_directory", data_dir
        )
        self.addCleanup(p.stop)
        p.start()

        self.service = CredentialsService(MagicMock())
        self.service._repo = MagicMock()
        self.enc = self.service._encryption  # real EncryptionService

    def _sealed(self, text: str) -> str:
        return self.enc.encrypt(text)


class ToDictStatusTests(_Base):
    def test_expired_status(self) -> None:
        cred = _credential(valid_until=(date.today() - timedelta(days=1)).isoformat())
        self.assertEqual(self.service._to_dict(cred)["status"], "expired")

    def test_unknown_status_for_unparseable_date(self) -> None:
        cred = _credential(valid_until="not-a-date")
        self.assertEqual(self.service._to_dict(cred)["status"], "unknown")


class UpdateCredentialTests(_Base):
    def test_not_found_raises(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = None
        with self.assertRaises(CredentialNotFoundError):
            self.service.update_credential(1, name="x", acting_user_id=1)

    def test_updates_scalar_fields_and_password(self) -> None:
        cred = _credential(type="ssh", visibility="global")
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service._repo.find_global_conflict.return_value = None
        self.service._repo.update.return_value = cred

        self.service.update_credential(
            1, name="renamed", username="root", cred_type="token",
            valid_until="2030-01-01", password="newpass", acting_user_id=1,
        )
        _args, kwargs = self.service._repo.update.call_args
        self.assertEqual(kwargs["name"], "renamed")
        self.assertEqual(kwargs["username"], "root")
        self.assertEqual(kwargs["type"], "token")
        self.assertIn("password_encrypted", kwargs)

    def test_rename_conflict_raises(self) -> None:
        cred = _credential(visibility="global")
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service._repo.find_global_conflict.return_value = _credential(id=99)
        with self.assertRaises(CredentialNameConflictError):
            self.service.update_credential(1, name="taken", acting_user_id=1)

    def test_visibility_change_to_private_without_owner_raises(self) -> None:
        cred = _credential(visibility="global", owner_user_id=None)
        self.service._repo.get_by_id_for_user.return_value = cred
        with self.assertRaises(CredentialMissingFieldError):
            self.service.update_credential(1, visibility="private", acting_user_id=None)

    def test_visibility_change_to_global_clears_owner(self) -> None:
        cred = _credential(visibility="private", owner_user_id=7)
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service._repo.find_global_conflict.return_value = None
        self.service._repo.update.return_value = cred
        self.service.update_credential(1, visibility="global", acting_user_id=7)
        _args, kwargs = self.service._repo.update.call_args
        self.assertEqual(kwargs["visibility"], "global")
        self.assertIsNone(kwargs["owner_user_id"])

    def test_ssh_key_update_triggers_export(self) -> None:
        cred = _credential(type="ssh_key", visibility="global")
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service._repo.find_global_conflict.return_value = None
        self.service._repo.update.return_value = cred
        with patch.object(self.service, "export_single_ssh_key") as export:
            self.service.update_credential(
                1, ssh_private_key="KEY", ssh_passphrase="pp", acting_user_id=1
            )
        export.assert_called_once()


class DeleteCredentialTests(_Base):
    def test_not_found_raises(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = None
        with self.assertRaises(CredentialNotFoundError):
            self.service.delete_credential(1, acting_user_id=1)

    def test_plain_delete(self) -> None:
        cred = _credential(type="token")
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service.delete_credential(1, acting_user_id=1)
        self.service._repo.delete.assert_called_once_with(cred)

    def test_ssh_key_delete_removes_key_file(self) -> None:
        cred = _credential(type="ssh_key", name="my key", visibility="global")
        self.service._repo.get_by_id_for_user.return_value = cred
        key_dir = Path(self.service._ssh_keys_directory())
        key_dir.mkdir(parents=True)
        key_file = key_dir / "global_my_key"
        key_file.write_text("KEY")
        self.service.delete_credential(1, acting_user_id=1)
        self.assertFalse(key_file.exists())
        self.service._repo.delete.assert_called_once_with(cred)


class DecryptTests(_Base):
    def _with(self, cred: MagicMock) -> None:
        self.service._repo.get_by_id_for_user.return_value = cred

    def test_get_decrypted_password(self) -> None:
        self._with(_credential(password_encrypted=self._sealed("s3cr3t")))
        self.assertEqual(self.service.get_decrypted_password(1), "s3cr3t")

    def test_get_decrypted_password_missing_raises(self) -> None:
        self._with(_credential(password_encrypted=None))
        with self.assertRaises(CredentialMissingFieldError):
            self.service.get_decrypted_password(1)

    def test_get_decrypted_password_not_found(self) -> None:
        self._with(None)
        with self.assertRaises(CredentialNotFoundError):
            self.service.get_decrypted_password(1)

    def test_get_decrypted_ssh_key(self) -> None:
        self._with(_credential(ssh_key_encrypted=self._sealed("PRIVATE")))
        self.assertEqual(self.service.get_decrypted_ssh_key(1), "PRIVATE")

    def test_get_decrypted_ssh_key_missing_raises(self) -> None:
        self._with(_credential(ssh_key_encrypted=None))
        with self.assertRaises(CredentialMissingFieldError):
            self.service.get_decrypted_ssh_key(1)

    def test_get_decrypted_ssh_passphrase_present_and_absent(self) -> None:
        self._with(_credential(ssh_passphrase_encrypted=self._sealed("pp")))
        self.assertEqual(self.service.get_decrypted_ssh_passphrase(1), "pp")
        self._with(_credential(ssh_passphrase_encrypted=None))
        self.assertIsNone(self.service.get_decrypted_ssh_passphrase(1))

    def test_get_decrypted_ssh_passphrase_not_found(self) -> None:
        self._with(None)
        with self.assertRaises(CredentialNotFoundError):
            self.service.get_decrypted_ssh_passphrase(1)


class SshKeyExportTests(_Base):
    def test_export_single_ssh_key_writes_file_with_mode_600(self) -> None:
        cred = _credential(
            id=3, type="ssh_key", name="edge/router", visibility="private",
            owner_user_id=8, ssh_key_encrypted=self._sealed("KEYDATA"),
        )
        self.service._repo.get_by_id_for_user.return_value = cred
        path = self.service.export_single_ssh_key(3, acting_user_id=8)
        self.assertTrue(path.endswith("user8_edge_router"))
        content = Path(path).read_text()
        self.assertEqual(content, "KEYDATA\n")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), oct(0o600))

    def test_export_single_ssh_key_missing_credential(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = None
        self.assertIsNone(self.service.export_single_ssh_key(1))

    def test_export_single_ssh_key_wrong_type(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = _credential(type="token")
        self.assertIsNone(self.service.export_single_ssh_key(1))

    def test_export_single_ssh_key_decrypt_error_returns_none(self) -> None:
        cred = _credential(type="ssh_key", ssh_key_encrypted="corrupt")
        self.service._repo.get_by_id_for_user.return_value = cred
        self.assertIsNone(self.service.export_single_ssh_key(1))

    def test_get_ssh_key_path_returns_existing_file(self) -> None:
        cred = _credential(
            type="ssh_key", name="rtr", visibility="global",
            ssh_key_encrypted=self._sealed("K"),
        )
        self.service._repo.get_by_id_for_user.return_value = cred
        key_dir = Path(self.service._ssh_keys_directory())
        key_dir.mkdir(parents=True)
        (key_dir / "global_rtr").write_text("K")
        self.assertTrue(self.service.get_ssh_key_path(1).endswith("global_rtr"))

    def test_get_ssh_key_path_exports_when_missing(self) -> None:
        cred = _credential(
            type="ssh_key", name="rtr", visibility="global",
            ssh_key_encrypted=self._sealed("K"),
        )
        self.service._repo.get_by_id_for_user.return_value = cred
        self.assertTrue(self.service.get_ssh_key_path(1).endswith("global_rtr"))

    def test_get_ssh_key_path_wrong_type_returns_none(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = _credential(type="token")
        self.assertIsNone(self.service.get_ssh_key_path(1))

    def test_filename_prefix_variants(self) -> None:
        self.assertEqual(self.service._ssh_key_filename_prefix("global", None), "global_")
        self.assertEqual(self.service._ssh_key_filename_prefix("private", 4), "user4_")
        self.assertEqual(self.service._ssh_key_filename_prefix("private", None), "private_")

    def test_delete_ssh_key_file_missing_returns_false(self) -> None:
        self.assertFalse(
            self.service._delete_ssh_key_file("ghost", "global", None)
        )


if __name__ == "__main__":
    unittest.main()
