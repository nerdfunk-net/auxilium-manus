"""Tests for ISESourceConfigService: keeps the settings row and encrypted
credential in sync for a Cisco ISE source (mocked repository/credential layers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.ise.source_config_service import (
    ISESourceConfigService,
    ISESourceConflictError,
    ISESourceNotFoundError,
)


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class ISESourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.ise.source_config_service.SettingsRepository")
        credentials_patcher = patch("services.ise.source_config_service.CredentialsService")
        self.mock_settings_cls = settings_patcher.start()
        self.mock_credentials_cls = credentials_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.addCleanup(credentials_patcher.stop)

        self.mock_settings = self.mock_settings_cls.return_value
        self.mock_credentials = self.mock_credentials_cls.return_value

        self.service = ISESourceConfigService(db=MagicMock())

    def test_create_source_creates_credential_then_setting(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_credentials.create_credential.return_value = {"id": 7, "username": "admin"}
        self.mock_settings.create.return_value = _setting(
            "sources.ise.lab",
            {
                "url": "https://10.10.20.77",
                "verify_ssl": False,
                "timeout": 30.0,
                "credential_id": 7,
                "source_id": "lab",
                "source_type": "ise",
            },
        )

        result = self.service.create_source(
            source_id="lab",
            url="https://10.10.20.77/",
            username="admin",
            password="C1sco12345!",
            verify_ssl=False,
        )

        self.mock_credentials.create_credential.assert_called_once_with(
            name="ise-lab",
            username="admin",
            cred_type="generic",
            password="C1sco12345!",
            source="ise",
        )
        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.ise.lab")
        self.assertEqual(create_kwargs["value"]["url"], "https://10.10.20.77")
        self.assertEqual(create_kwargs["value"]["credential_id"], 7)
        self.assertNotIn("credential_id", result)
        self.assertNotIn("password", result)

    def test_create_source_conflict_raises_without_creating_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.ise.lab", {})
        with self.assertRaises(ISESourceConflictError):
            self.service.create_source(
                source_id="lab", url="https://x", username="admin", password="pw"
            )
        self.mock_credentials.create_credential.assert_not_called()

    def test_update_source_blank_password_keeps_existing_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.ise.lab",
            {"url": "https://10.10.20.77", "verify_ssl": True, "timeout": 30.0, "credential_id": 7},
        )
        self.mock_settings.update.return_value = _setting(
            "sources.ise.lab",
            {"url": "https://10.10.20.99", "verify_ssl": True, "timeout": 30.0, "credential_id": 7},
        )

        result = self.service.update_source("lab", url="https://10.10.20.99")

        self.mock_credentials.update_credential.assert_not_called()
        self.assertEqual(result["url"], "https://10.10.20.99")

    def test_update_source_with_password_updates_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.ise.lab",
            {"url": "https://10.10.20.77", "verify_ssl": True, "timeout": 30.0, "credential_id": 7},
        )
        self.mock_settings.update.return_value = _setting("sources.ise.lab", {"credential_id": 7})

        self.service.update_source("lab", password="new-password")

        self.mock_credentials.update_credential.assert_called_once_with(
            7, username=None, password="new-password"
        )

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(ISESourceNotFoundError):
            self.service.update_source("missing", url="https://x")

    def test_delete_source_removes_setting_and_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.ise.lab", {"credential_id": 7}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()
        self.mock_credentials.delete_credential.assert_called_once_with(7)

    def test_resolve_credentials_returns_decrypted_password(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.ise.lab",
            {
                "url": "https://10.10.20.77",
                "verify_ssl": False,
                "timeout": 15.0,
                "credential_id": 7,
            },
        )
        self.mock_credentials.get_credential_by_id.return_value = {
            "id": 7,
            "username": "admin",
        }
        self.mock_credentials.get_decrypted_password.return_value = "C1sco12345!"

        creds = self.service.resolve_credentials("lab")

        self.assertEqual(creds.base_url, "https://10.10.20.77")
        self.assertEqual(creds.username, "admin")
        self.assertEqual(creds.password, "C1sco12345!")
        self.assertFalse(creds.verify_ssl)
        self.assertEqual(creds.timeout, 15.0)

    def test_list_sources_hides_credential_id(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.ise.lab", {"url": "https://x", "credential_id": 7}),
        ]
        result = self.service.list_sources()
        self.assertNotIn("credential_id", result[0])


if __name__ == "__main__":
    unittest.main()
