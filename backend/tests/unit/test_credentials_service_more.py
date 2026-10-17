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
    CredentialInUseError,
    CredentialMissingFieldError,
    CredentialNameConflictError,
    CredentialNotFoundError,
)
from services.credentials.usage import CredentialDependant


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
        key_file = key_dir / "global_1"
        key_file.write_text("KEY")
        self.service.delete_credential(1, acting_user_id=1)
        self.assertFalse(key_file.exists())
        self.service._repo.delete.assert_called_once_with(cred)


class DeleteInUseTests(_Base):
    """O1-04: a credential that something still uses is not deleted without ``force``."""

    DEPENDANTS = [
        CredentialDependant("git_repository", 3, "configs"),
        CredentialDependant("workflow", 8, "Backup"),
    ]

    def setUp(self) -> None:
        super().setUp()
        patcher = patch(
            "services.credentials.credentials_service.find_dependants",
            return_value=list(self.DEPENDANTS),
        )
        self.find = patcher.start()
        self.addCleanup(patcher.stop)
        self.cred = _credential(type="token")
        self.service._repo.get_by_id_for_user.return_value = self.cred

    def test_refuses_and_reports_the_dependants(self) -> None:
        with self.assertRaises(CredentialInUseError) as caught:
            self.service.delete_credential(1, acting_user_id=1)
        self.assertEqual(caught.exception.dependants, self.DEPENDANTS)
        self.service._repo.delete.assert_not_called()

    def test_refusal_happens_before_the_vault_secret_is_touched(self) -> None:
        self.cred.storage_backend = "vault"
        self.cred.vault_path = "credentials/lab-1"
        writer = MagicMock()
        self.service._vault_writer = writer
        with self.assertRaises(CredentialInUseError):
            self.service.delete_credential(1, acting_user_id=1)
        writer.delete_kv.assert_not_called()

    def test_force_deletes_anyway_and_still_audits(self) -> None:
        with patch.object(CredentialsService, "audit") as audit:
            self.service.delete_credential(1, acting_user_id=1, force=True)
        self.service._repo.delete.assert_called_once_with(self.cred)
        audit.assert_called_once_with("delete", 1, 1)

    def test_force_skips_the_lookup(self) -> None:
        self.service.delete_credential(1, acting_user_id=1, force=True)
        self.find.assert_not_called()

    def test_no_dependants_deletes(self) -> None:
        self.find.return_value = []
        self.service.delete_credential(1, acting_user_id=1)
        self.service._repo.delete.assert_called_once_with(self.cred)



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
        self.assertTrue(path.endswith("user8_3"))
        self.assertEqual(oct(os.stat(Path(path).parent).st_mode & 0o777), oct(0o700))
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
        (key_dir / "global_1").write_text("K")
        self.assertTrue(self.service.get_ssh_key_path(1).endswith("global_1"))

    def test_get_ssh_key_path_exports_when_missing(self) -> None:
        cred = _credential(
            type="ssh_key", name="rtr", visibility="global",
            ssh_key_encrypted=self._sealed("K"),
        )
        self.service._repo.get_by_id_for_user.return_value = cred
        self.assertTrue(self.service.get_ssh_key_path(1).endswith("global_1"))

    def test_get_ssh_key_path_wrong_type_returns_none(self) -> None:
        self.service._repo.get_by_id_for_user.return_value = _credential(type="token")
        self.assertIsNone(self.service.get_ssh_key_path(1))

    def test_filename_variants(self) -> None:
        self.assertEqual(self.service._ssh_key_filename(5, "global", None), "global_5")
        self.assertEqual(self.service._ssh_key_filename(5, "private", 4), "user4_5")
        self.assertEqual(self.service._ssh_key_filename(5, "private", None), "private_5")

    def test_delete_ssh_key_files_missing_is_a_noop(self) -> None:
        self.service._delete_ssh_key_files(999)  # no directory, no error

    def test_alike_names_get_distinct_key_files(self) -> None:
        a = _credential(id=1, type="ssh_key", name="prod.key", visibility="global",
                        ssh_key_encrypted=self._sealed("KEY-A"))
        b = _credential(id=2, type="ssh_key", name="prod_key", visibility="global",
                        ssh_key_encrypted=self._sealed("KEY-B"))
        self.service._repo.get_by_id_for_user.return_value = a
        path_a = self.service.export_single_ssh_key(1)
        self.service._repo.get_by_id_for_user.return_value = b
        path_b = self.service.export_single_ssh_key(2)
        self.assertNotEqual(path_a, path_b)
        self.assertEqual(Path(path_a).read_text(), "KEY-A\n")
        self.assertEqual(Path(path_b).read_text(), "KEY-B\n")

    def test_files_of_every_visibility_prefix_are_removed(self) -> None:
        key_dir = Path(self.service._ssh_keys_directory())
        key_dir.mkdir(parents=True)
        for name in ("global_7", "user3_7", "private_7", "global_70"):
            (key_dir / name).write_text("K")
        self.service._delete_ssh_key_files(7)
        self.assertEqual(sorted(p.name for p in key_dir.iterdir()), ["global_70"])


if __name__ == "__main__":
    unittest.main()


class AuditAndLifecycleTests(_Base):
    def test_audit_line_contains_ids_only(self) -> None:
        cred = _credential(id=9, type="token", name="very-secret-name")
        self.service._repo.get_by_id_for_user.return_value = cred
        with self.assertLogs("services.credentials.credentials_service", level="INFO") as logs:
            self.service.delete_credential(9, acting_user_id=4)
        text = "\n".join(logs.output)
        self.assertIn("credential_audit action=delete user_id=4 credential_id=9", text)
        self.assertNotIn("very-secret-name", text)

    def test_rename_removes_the_old_key_file(self) -> None:
        cred = _credential(
            id=5, type="ssh_key", name="old", visibility="global",
            ssh_key_encrypted=self._sealed("K"), storage_backend="local",
        )
        self.service._repo.get_by_id_for_user.return_value = cred
        self.service._repo.update.return_value = cred
        key_dir = Path(self.service._ssh_keys_directory())
        key_dir.mkdir(parents=True)
        stale = key_dir / "user3_5"  # exported while the credential was private
        stale.write_text("K")
        self.service._repo.find_global_conflict.return_value = None
        self.service.update_credential(5, name="new", acting_user_id=3)
        self.assertFalse(stale.exists())
        self.assertTrue((key_dir / "global_5").exists())
