"""storage_backend dispatch in CredentialsService (local vs OpenBao)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.credentials import Credential
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialStorageBackendChangeError,
    CredentialVaultNotConfiguredError,
    CredentialVaultUnavailableError,
)
from services.vault.exceptions import VaultUnavailableError


class CredentialsServiceVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Credential.__table__])
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.reader = MagicMock()
        self.writer = MagicMock()
        self.service = CredentialsService(
            self.db, vault_reader=self.reader, vault_writer=self.writer
        )

    def _row(self, name: str) -> Credential:
        return self.db.scalar(select(Credential).where(Credential.name == name))

    # --------------------------------------------------------------------- create
    def test_create_vault_token_credential_writes_to_openbao(self) -> None:
        result = self.service.create_credential(
            name="lab-token",
            username="svc",
            cred_type="token",
            password="tok-123",
            visibility="global",
            storage_backend="vault",
        )
        row = self._row("lab-token")
        self.assertEqual(row.storage_backend, "vault")
        self.assertEqual(row.vault_path, f"credentials/lab-token-{row.id}")
        self.assertEqual(row.vault_secret_fields, "token")
        self.assertIsNone(row.password_encrypted)
        self.writer.write_kv.assert_called_once_with(
            f"credentials/lab-token-{row.id}", {"token": "tok-123"}
        )
        self.assertEqual(result["storage_backend"], "vault")
        self.assertTrue(result["has_password"])

    def test_create_vault_without_writer_raises(self) -> None:
        service = CredentialsService(self.db, vault_reader=self.reader, vault_writer=None)
        with self.assertRaises(CredentialVaultNotConfiguredError):
            service.create_credential(
                name="x",
                username="u",
                cred_type="token",
                password="t",
                visibility="global",
                storage_backend="vault",
            )

    def test_create_vault_rolls_back_when_openbao_write_fails(self) -> None:
        self.writer.write_kv.side_effect = VaultUnavailableError("sealed")
        with self.assertRaises(CredentialVaultUnavailableError):
            self.service.create_credential(
                name="doomed",
                username="u",
                cred_type="token",
                password="t",
                visibility="global",
                storage_backend="vault",
            )
        self.assertIsNone(self._row("doomed"))

    # -------------------------------------------------------------------- resolve
    def test_get_decrypted_password_reads_from_vault(self) -> None:
        self.service.create_credential(
            name="lab-token",
            username="svc",
            cred_type="token",
            password="tok-123",
            visibility="global",
            storage_backend="vault",
        )
        row = self._row("lab-token")
        self.reader.read_kv.return_value = {"token": "tok-123"}

        value = self.service.get_decrypted_password(row.id)

        self.assertEqual(value, "tok-123")
        self.reader.read_kv.assert_called_once_with(row.vault_path)

    def test_local_credential_still_round_trips(self) -> None:
        self.service.create_credential(
            name="local-pw",
            username="admin",
            cred_type="ssh",
            password="p@ss",
            visibility="global",
            storage_backend="local",
        )
        row = self._row("local-pw")
        self.assertEqual(row.storage_backend, "local")
        self.assertIsNotNone(row.password_encrypted)
        self.assertEqual(self.service.get_decrypted_password(row.id), "p@ss")
        self.reader.read_kv.assert_not_called()

    def test_vault_unavailable_fails_closed_but_local_still_resolves(self) -> None:
        self.service.create_credential(
            name="vault-pw",
            username="svc",
            cred_type="token",
            password="v",
            visibility="global",
            storage_backend="vault",
        )
        self.service.create_credential(
            name="local-pw",
            username="admin",
            cred_type="ssh",
            password="l",
            visibility="global",
            storage_backend="local",
        )
        vault_id = self._row("vault-pw").id
        local_id = self._row("local-pw").id
        self.reader.read_kv.side_effect = VaultUnavailableError("connection refused")

        with self.assertRaises(CredentialVaultUnavailableError):
            self.service.get_decrypted_password(vault_id)
        self.assertEqual(self.service.get_decrypted_password(local_id), "l")

    def test_ssh_key_path_written_from_vault_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import core.config

            original = core.config.settings.data_directory
            core.config.settings.data_directory = Path(tmp)
            try:
                self.service.create_credential(
                    name="lab-key",
                    username="git",
                    cred_type="ssh_key",
                    ssh_private_key="-----BEGIN KEY-----\nabc\n-----END KEY-----",
                    ssh_passphrase="pp",
                    visibility="global",
                    storage_backend="vault",
                )
                row = self._row("lab-key")
                self.assertEqual(row.vault_secret_fields, "ssh_key,ssh_passphrase")
                self.reader.read_kv.return_value = {
                    "ssh_key": "-----BEGIN KEY-----\nabc\n-----END KEY-----",
                    "ssh_passphrase": "pp",
                }
                path = self.service.get_ssh_key_path(row.id)
                self.assertTrue(Path(path).exists())
                self.assertIn("abc", Path(path).read_text())
            finally:
                core.config.settings.data_directory = original

    # --------------------------------------------------------------------- update
    def test_update_rejects_storage_backend_change(self) -> None:
        self.service.create_credential(
            name="v",
            username="u",
            cred_type="token",
            password="t",
            visibility="global",
            storage_backend="vault",
        )
        row = self._row("v")
        with self.assertRaises(CredentialStorageBackendChangeError):
            self.service.update_credential(row.id, storage_backend="local")

    def test_update_vault_secret_merges_fields(self) -> None:
        self.service.create_credential(
            name="v",
            username="u",
            cred_type="ssh_key",
            ssh_private_key="KEY",
            visibility="global",
            storage_backend="vault",
        )
        row = self._row("v")
        self.writer.read_kv.return_value = {"ssh_key": "KEY"}

        self.service.update_credential(row.id, ssh_passphrase="new-pp")

        self.writer.write_kv.assert_called_with(
            row.vault_path, {"ssh_key": "KEY", "ssh_passphrase": "new-pp"}
        )
        self.assertEqual(self._row("v").vault_secret_fields, "ssh_key,ssh_passphrase")

    # --------------------------------------------------------------------- delete
    def test_delete_vault_credential_removes_openbao_secret(self) -> None:
        self.service.create_credential(
            name="v",
            username="u",
            cred_type="token",
            password="t",
            visibility="global",
            storage_backend="vault",
        )
        row = self._row("v")
        path = row.vault_path
        self.service.delete_credential(row.id)
        self.writer.delete_kv.assert_called_once_with(path)
        self.assertIsNone(self._row("v"))


if __name__ == "__main__":
    unittest.main()
