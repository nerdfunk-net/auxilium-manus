"""Secret redaction in repr, secret length bounds, worker vault startup and SecretID file mode."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from models.credentials import (
    MAX_PASSWORD_LENGTH,
    MAX_SSH_KEY_LENGTH,
    CredentialCreate,
    CredentialUpdate,
)
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.infisical_client import _InfisicalToken
from services.vault.auth import VaultToken
from services.vault.config import VaultConfig

SECRET = "sup3r-s3cret-value"


class SecretNotInReprTests(unittest.TestCase):
    def test_vault_token(self) -> None:
        self.assertNotIn(SECRET, repr(VaultToken(client_token=SECRET)))

    def test_vault_config(self) -> None:
        cfg = VaultConfig(
            addr="https://v", mount="m", secret_id=SECRET, token=SECRET, client_key=SECRET
        )
        self.assertNotIn(SECRET, repr(cfg))

    def test_infisical_token(self) -> None:
        self.assertNotIn(SECRET, repr(_InfisicalToken(access_token=SECRET, expires_at=1.0)))

    def test_secret_manager_config(self) -> None:
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(SecretManagerConnectionConfig)}
        self.assertIn("auth_secret", field_names)
        field = next(
            f for f in dataclasses.fields(SecretManagerConnectionConfig) if f.name == "auth_secret"
        )
        self.assertFalse(field.repr)


class SecretLengthBoundTests(unittest.TestCase):
    def test_password_and_key_bounds_on_create_and_update(self) -> None:
        with self.assertRaises(ValidationError):
            CredentialUpdate(password="x" * (MAX_PASSWORD_LENGTH + 1))
        with self.assertRaises(ValidationError):
            CredentialUpdate(ssh_private_key="x" * (MAX_SSH_KEY_LENGTH + 1))
        with self.assertRaises(ValidationError):
            CredentialUpdate(ssh_passphrase="x" * (MAX_PASSWORD_LENGTH + 1))
        with self.assertRaises(ValidationError):
            CredentialCreate(
                name="n", type="generic", password="x" * (MAX_PASSWORD_LENGTH + 1)
            )

    def test_values_at_the_bound_are_accepted(self) -> None:
        CredentialUpdate(password="x" * MAX_PASSWORD_LENGTH)
        CredentialUpdate(ssh_private_key="x" * MAX_SSH_KEY_LENGTH)


class WorkerVaultStartupTests(unittest.TestCase):
    def test_workers_skip_management_client(self) -> None:
        import service_factory
        from core import vault

        runtime = AsyncMock()
        with (
            patch.object(vault.settings, "vault_enabled", True),
            patch.object(vault, "build_vault_config"),
            patch.object(vault, "build_vault_management_config") as build_mgmt,
            patch("services.vault.client.OpenBaoService", return_value=runtime),
            patch.object(service_factory, "set_vault_service") as set_runtime,
            patch.object(service_factory, "set_vault_management_service") as set_mgmt,
        ):
            asyncio.run(vault.start_vault_services(with_management=False))
        set_runtime.assert_called_once_with(runtime)
        build_mgmt.assert_not_called()
        set_mgmt.assert_not_called()

    def test_api_starts_both_clients(self) -> None:
        import service_factory
        from core import vault

        with (
            patch.object(vault.settings, "vault_enabled", True),
            patch.object(vault, "build_vault_config"),
            patch.object(vault, "build_vault_management_config"),
            patch("services.vault.client.OpenBaoService", return_value=AsyncMock()),
            patch.object(service_factory, "set_vault_service"),
            patch.object(service_factory, "set_vault_management_service") as set_mgmt,
        ):
            asyncio.run(vault.start_vault_services())
        set_mgmt.assert_called_once()


class SecretIdFileModeTests(unittest.TestCase):
    def _cfg(self, path: str) -> VaultConfig:
        return VaultConfig(addr="https://v", mount="m", secret_id_file=path)

    def test_group_readable_secret_id_file_warns(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("sid\n")
        self.addCleanup(os.unlink, handle.name)
        os.chmod(handle.name, 0o640)
        with self.assertLogs("services.vault.config", level=logging.WARNING):
            self.assertEqual(self._cfg(handle.name).resolved_secret_id(), "sid")

    def test_private_secret_id_file_does_not_warn(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("sid")
        self.addCleanup(os.unlink, handle.name)
        os.chmod(handle.name, 0o600)
        with self.assertNoLogs("services.vault.config", level=logging.WARNING):
            self.assertEqual(self._cfg(handle.name).resolved_secret_id(), "sid")


if __name__ == "__main__":
    unittest.main()
