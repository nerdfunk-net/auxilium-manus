"""Tests for the CredentialManager facade (services.credentials.manager)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialVaultUnavailableError,
)
from services.credentials.manager import CredentialManager
from services.credentials.secrets import (
    CredentialLookupError,
    CredentialUnusableError,
    GenericSecret,
    GitSecret,
    SharedSecret,
    SourceSecret,
    SshSecret,
)


def _credential(cred_id: int = 1, *, name: str, cred_type: str, status: str = "active") -> dict:
    return {
        "id": cred_id,
        "name": name,
        "type": cred_type,
        "status": status,
        "username": "admin",
    }


class CredentialManagerTestBase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("services.credentials.manager.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value

    def _manager(self, acting_user_id: int | None = 1) -> CredentialManager:
        return CredentialManager(MagicMock(), acting_user_id=acting_user_id)


class SshTests(CredentialManagerTestBase):
    def test_resolves_ssh_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        secret = self._manager().ssh("lab-ssh")

        self.assertEqual(secret, SshSecret(username="admin", password="secret"))

    def test_scopes_list_to_general_source_and_acting_user(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        self._manager(acting_user_id=7).ssh("lab-ssh")

        self.mock_service.list_credentials.assert_called_once_with(
            include_expired=False, source="general", acting_user_id=7
        )
        self.mock_service.get_decrypted_password.assert_called_once_with(
            1, acting_user_id=7
        )

    def test_rejects_generic_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-generic", cred_type="generic")
        ]
        with self.assertRaises(CredentialUnusableError):
            self._manager().ssh("lab-generic")

    def test_not_found_raises_lookup_error(self) -> None:
        self.mock_service.list_credentials.return_value = []
        with self.assertRaises(CredentialLookupError):
            self._manager().ssh("missing")

    def test_blank_reference_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self._manager().ssh("   ")

    def test_expired_raises_unusable_error(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh", status="expired")
        ]
        with self.assertRaises(CredentialUnusableError):
            self._manager().ssh("lab-ssh")

    def test_missing_password_raises_unusable_error(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.side_effect = CredentialMissingFieldError(
            "none"
        )
        with self.assertRaises(CredentialUnusableError):
            self._manager().ssh("lab-ssh")

    def test_private_credential_wins_over_global_of_same_name(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {**_credential(1, name="shared", cred_type="ssh"), "visibility": "global"},
            {
                **_credential(2, name="shared", cred_type="ssh"),
                "username": "owner",
                "visibility": "private",
            },
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        secret = self._manager().ssh("shared")

        self.assertEqual(secret.username, "owner")
        self.mock_service.get_decrypted_password.assert_called_once_with(2, acting_user_id=1)

    def test_acting_user_none_scopes_to_global(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        self._manager(acting_user_id=None).ssh("lab-ssh")

        self.mock_service.list_credentials.assert_called_once_with(
            include_expired=False, source="general", acting_user_id=None
        )


class GenericTests(CredentialManagerTestBase):
    def test_accepts_ssh_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        secret = self._manager().generic("lab-ssh")

        self.assertEqual(secret, GenericSecret(username="admin", password="secret"))

    def test_accepts_generic_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-generic", cred_type="generic")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        secret = self._manager().generic("lab-generic")

        self.assertEqual(secret.password, "secret")

    def test_rejects_ssh_key_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-key", cred_type="ssh_key")
        ]
        with self.assertRaises(CredentialUnusableError):
            self._manager().generic("lab-key")


class SharedSecretTests(CredentialManagerTestBase):
    def test_returns_algorithm_and_passphrase(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {
                **_credential(name="vault", cred_type="shared_secret"),
                "algorithm": "aes-256-gcm",
            }
        ]
        self.mock_service.get_decrypted_password.return_value = "the-passphrase"

        secret = self._manager().shared_secret("vault")

        self.assertEqual(
            secret, SharedSecret(algorithm="aes-256-gcm", passphrase="the-passphrase")
        )

    def test_defaults_algorithm_when_missing(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="vault", cred_type="shared_secret")
        ]
        self.mock_service.get_decrypted_password.return_value = "pw"

        secret = self._manager().shared_secret("vault")

        self.assertEqual(secret.algorithm, "aes-256-gcm")

    def test_rejects_non_shared_secret_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="vault", cred_type="ssh")
        ]
        with self.assertRaises(CredentialUnusableError):
            self._manager().shared_secret("vault")


class SourceCredentialTests(CredentialManagerTestBase):
    def test_source_credential_returns_global_row(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "u",
        }
        result = self._manager().source_credential(3)
        self.assertEqual(result["id"], 3)
        self.mock_service.get_credential_by_id.assert_called_once_with(3)

    def test_source_credential_rejects_missing(self) -> None:
        self.mock_service.get_credential_by_id.return_value = None
        with self.assertRaises(CredentialLookupError):
            self._manager().source_credential(3)

    def test_source_credential_rejects_private(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "private",
        }
        with self.assertRaises(CredentialLookupError):
            self._manager().source_credential(3)

    def test_source_secret_returns_username_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.return_value = "s3cr3t"

        secret = self._manager().source_secret(3)

        self.assertEqual(secret, SourceSecret(username="admin", password="s3cr3t"))
        self.mock_service.get_decrypted_password.assert_called_once_with(3)

    def test_source_secret_rejects_credential_without_password(self) -> None:
        self.mock_service.get_credential_by_id.return_value = {
            "id": 3,
            "visibility": "global",
            "username": "admin",
        }
        self.mock_service.get_decrypted_password.side_effect = CredentialMissingFieldError(
            "none"
        )
        with self.assertRaises(CredentialUnusableError):
            self._manager().source_secret(3)


class GitTests(CredentialManagerTestBase):
    def test_no_credential_name_returns_empty(self) -> None:
        secret = self._manager().git({"auth_type": "token"})
        self.assertEqual(secret, GitSecret(None, None, None))
        self.mock_service.list_credentials.assert_not_called()

    def test_token_auth_resolves(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 1, "name": "deploy-token", "type": "token", "username": "git"}
        ]
        self.mock_service.get_decrypted_password.return_value = "shh"

        secret = self._manager().git(
            {"auth_type": "token", "credential_name": "deploy-token"}
        )

        self.assertEqual(secret, GitSecret(username="git", token="shh", ssh_key_path=None))
        self.mock_service.list_credentials.assert_called_once_with(
            include_expired=False, acting_user_id=None
        )
        self.mock_service.get_decrypted_password.assert_called_once_with(
            1, acting_user_id=None
        )

    def test_default_auth_type_is_token(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 1, "name": "t", "type": "token", "username": "git"}
        ]
        self.mock_service.get_decrypted_password.return_value = "shh"

        secret = self._manager().git({"credential_name": "t"})

        self.assertEqual(secret.token, "shh")

    def test_generic_auth_resolves(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 2, "name": "g", "type": "generic", "username": "u"}
        ]
        self.mock_service.get_decrypted_password.return_value = "pw"

        secret = self._manager().git({"auth_type": "generic", "credential_name": "g"})

        self.assertEqual(secret, GitSecret(username="u", token="pw", ssh_key_path=None))

    def test_ssh_key_auth_resolves_path(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 3, "name": "k", "type": "ssh_key", "username": "git"}
        ]
        self.mock_service.get_ssh_key_path.return_value = "/tmp/keys/k"

        secret = self._manager().git({"auth_type": "ssh_key", "credential_name": "k"})

        self.assertEqual(
            secret, GitSecret(username="git", token=None, ssh_key_path="/tmp/keys/k")
        )
        self.mock_service.get_ssh_key_path.assert_called_once_with(3, acting_user_id=None)

    def test_ssh_key_auth_missing_key_file_returns_empty(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 3, "name": "k", "type": "ssh_key", "username": "git"}
        ]
        self.mock_service.get_ssh_key_path.return_value = None

        secret = self._manager().git({"auth_type": "ssh_key", "credential_name": "k"})

        self.assertEqual(secret, GitSecret(None, None, None))

    def test_private_only_match_treated_as_not_found(self) -> None:
        self.mock_service.list_credentials.return_value = []

        secret = self._manager().git(
            {"auth_type": "token", "credential_name": "someone-elses-private"}
        )

        self.assertEqual(secret, GitSecret(None, None, None))

    def test_wrong_type_for_auth_type_is_not_a_match(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 1, "name": "x", "type": "ssh_key", "username": "git"}
        ]

        secret = self._manager().git({"auth_type": "token", "credential_name": "x"})

        self.assertEqual(secret, GitSecret(None, None, None))

    def test_vault_unavailable_propagates(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 1, "name": "t", "type": "token", "username": "git"}
        ]
        self.mock_service.get_decrypted_password.side_effect = (
            CredentialVaultUnavailableError()
        )

        with self.assertRaises(CredentialVaultUnavailableError):
            self._manager().git({"auth_type": "token", "credential_name": "t"})

    def test_decrypt_failure_returns_empty(self) -> None:
        self.mock_service.list_credentials.return_value = [
            {"id": 1, "name": "t", "type": "token", "username": "git"}
        ]
        self.mock_service.get_decrypted_password.side_effect = RuntimeError("boom")

        secret = self._manager().git({"auth_type": "token", "credential_name": "t"})

        self.assertEqual(secret, GitSecret(None, None, None))


if __name__ == "__main__":
    unittest.main()
