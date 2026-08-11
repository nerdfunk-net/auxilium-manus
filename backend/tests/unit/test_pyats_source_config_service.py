"""Tests for PyATSSourceConfigService: keeps the settings row and encrypted
credential in sync for a pyATS shim source (mocked repository/credential layers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceConflictError,
    PyATSSourceNotFoundError,
)


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class PyATSSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.pyats.source_config_service.SettingsRepository")
        credentials_patcher = patch("services.pyats.source_config_service.CredentialsService")
        validate_patcher = patch(
            "services.pyats.source_config_service.validate_outbound_http_url",
            side_effect=lambda url, resolve_dns=True: (url or "").rstrip("/"),
        )
        self.mock_settings_cls = settings_patcher.start()
        self.mock_credentials_cls = credentials_patcher.start()
        validate_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.addCleanup(credentials_patcher.stop)
        self.addCleanup(validate_patcher.stop)

        self.mock_settings = self.mock_settings_cls.return_value
        self.mock_credentials = self.mock_credentials_cls.return_value

        self.service = PyATSSourceConfigService(db=MagicMock())

    def test_create_source_creates_credential_then_setting(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_credentials.create_credential.return_value = {"id": 7, "username": "pyats-shim"}
        self.mock_settings.create.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:8100",
                "verify_ssl": False,
                "timeout": 30.0,
                "credential_id": 7,
                "source_id": "lab",
                "source_type": "pyats",
            },
        )

        result = self.service.create_source(
            source_id="lab",
            url="http://pyats-shim:8100/",
            token="s3cr3t-token",
        )

        self.mock_credentials.create_credential.assert_called_once_with(
            name="pyats-lab",
            username="pyats-shim",
            cred_type="generic",
            password="s3cr3t-token",
            source="pyats",
            visibility="global",
        )
        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.pyats.lab")
        self.assertEqual(create_kwargs["value"]["url"], "http://pyats-shim:8100")
        self.assertEqual(create_kwargs["value"]["credential_id"], 7)
        self.assertNotIn("credential_id", result)
        self.assertNotIn("token", result)

    def test_create_source_conflict_raises_without_creating_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.pyats.lab", {})
        with self.assertRaises(PyATSSourceConflictError):
            self.service.create_source(source_id="lab", url="http://x", token="tok")
        self.mock_credentials.create_credential.assert_not_called()

    def test_update_source_blank_token_keeps_existing_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:8100",
                "verify_ssl": False,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )
        self.mock_settings.update.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:9000",
                "verify_ssl": False,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )

        result = self.service.update_source("lab", url="http://pyats-shim:9000")

        self.mock_credentials.update_credential.assert_not_called()
        self.assertEqual(result["url"], "http://pyats-shim:9000")

    def test_update_source_with_token_updates_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:8100",
                "verify_ssl": False,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )
        self.mock_settings.update.return_value = _setting("sources.pyats.lab", {"credential_id": 7})

        self.service.update_source("lab", token="new-token")

        self.mock_credentials.update_credential.assert_called_once_with(7, password="new-token")

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(PyATSSourceNotFoundError):
            self.service.update_source("missing", url="http://x")

    def test_delete_source_removes_setting_and_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab", {"credential_id": 7}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()
        self.mock_credentials.delete_credential.assert_called_once_with(7)

    def test_resolve_credentials_returns_decrypted_token(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:8100",
                "verify_ssl": False,
                "timeout": 15.0,
                "credential_id": 7,
            },
        )
        self.mock_credentials.get_credential_by_id.return_value = {
            "id": 7,
            "username": "pyats-shim",
        }
        self.mock_credentials.get_decrypted_password.return_value = "s3cr3t-token"

        creds = self.service.resolve_credentials("lab")

        self.assertEqual(creds.base_url, "http://pyats-shim:8100")
        self.assertEqual(creds.token, "s3cr3t-token")
        self.assertFalse(creds.verify_ssl)
        self.assertEqual(creds.timeout, 15.0)

    def test_list_sources_hides_credential_id(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.pyats.lab", {"url": "http://x", "credential_id": 7}),
        ]
        result = self.service.list_sources()
        self.assertNotIn("credential_id", result[0])


if __name__ == "__main__":
    unittest.main()
