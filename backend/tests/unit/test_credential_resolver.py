"""Tests for workflow_steps.common.credential_resolver."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from workflow_steps.common.credential_resolver import (
    CredentialReferenceInvalidError,
    CredentialReferenceNotFoundError,
    resolve_generic_credential,
    resolve_ssh_credential,
)


def _credential(cred_id: int = 1, *, name: str, cred_type: str, status: str = "active") -> dict:
    return {"id": cred_id, "name": name, "type": cred_type, "status": status, "username": "admin"}


class ResolveSshCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("workflow_steps.common.credential_resolver.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value

    def test_resolves_ssh_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        username, password = resolve_ssh_credential(MagicMock(), "lab-ssh", acting_user_id=1)

        self.assertEqual(username, "admin")
        self.assertEqual(password, "secret")

    def test_rejects_generic_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-generic", cred_type="generic")
        ]
        with self.assertRaises(CredentialReferenceInvalidError):
            resolve_ssh_credential(MagicMock(), "lab-generic", acting_user_id=1)

    def test_not_found_raises(self) -> None:
        self.mock_service.list_credentials.return_value = []
        with self.assertRaises(CredentialReferenceNotFoundError):
            resolve_ssh_credential(MagicMock(), "missing", acting_user_id=1)

    def test_blank_reference_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_ssh_credential(MagicMock(), "   ", acting_user_id=1)

    def test_expired_raises(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh", status="expired")
        ]
        with self.assertRaises(CredentialReferenceInvalidError):
            resolve_ssh_credential(MagicMock(), "lab-ssh", acting_user_id=1)


class ResolveGenericCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("workflow_steps.common.credential_resolver.CredentialsService")
        self.mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_cls.return_value

    def test_accepts_ssh_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-ssh", cred_type="ssh")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        username, password = resolve_generic_credential(MagicMock(), "lab-ssh", acting_user_id=1)

        self.assertEqual(username, "admin")
        self.assertEqual(password, "secret")

    def test_accepts_generic_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-generic", cred_type="generic")
        ]
        self.mock_service.get_decrypted_password.return_value = "secret"

        username, password = resolve_generic_credential(
            MagicMock(), "lab-generic", acting_user_id=1
        )

        self.assertEqual(username, "admin")
        self.assertEqual(password, "secret")

    def test_rejects_ssh_key_type(self) -> None:
        self.mock_service.list_credentials.return_value = [
            _credential(name="lab-key", cred_type="ssh_key")
        ]
        with self.assertRaises(CredentialReferenceInvalidError):
            resolve_generic_credential(MagicMock(), "lab-key", acting_user_id=1)

    def test_not_found_raises(self) -> None:
        self.mock_service.list_credentials.return_value = []
        with self.assertRaises(CredentialReferenceNotFoundError):
            resolve_generic_credential(MagicMock(), "missing", acting_user_id=1)


if __name__ == "__main__":
    unittest.main()
