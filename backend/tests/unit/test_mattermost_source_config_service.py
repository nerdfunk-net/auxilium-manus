"""Tests for MattermostSourceConfigService: keeps the settings row and encrypted
credential in sync for a Mattermost source (mocked repository/credential layers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.safe_urls import UnsafeURLError
from services.mattermost.source_config_service import (
    MattermostSourceConfigService,
    MattermostSourceConflictError,
    MattermostSourceNotFoundError,
)


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class MattermostSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch(
            "services.mattermost.source_config_service.SettingsRepository"
        )
        credentials_patcher = patch(
            "services.mattermost.source_config_service.CredentialsService"
        )
        validate_patcher = patch(
            "services.mattermost.source_config_service.validate_outbound_http_url",
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

        self.service = MattermostSourceConfigService(db=MagicMock())

    def test_create_source_creates_credential_then_setting(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_credentials.create_credential.return_value = {
            "id": 7,
            "username": "mattermost-bot",
        }
        self.mock_settings.create.return_value = _setting(
            "sources.mattermost.lab",
            {
                "url": "http://localhost:8065",
                "verify_ssl": True,
                "timeout": 30.0,
                "credential_id": 7,
                "source_id": "lab",
                "source_type": "mattermost",
            },
        )

        result = self.service.create_source(
            source_id="lab",
            url="http://localhost:8065/",
            token="s3cr3t-token",
        )

        self.mock_credentials.create_credential.assert_called_once_with(
            name="mattermost-lab",
            username="mattermost-bot",
            cred_type="generic",
            password="s3cr3t-token",
            source="mattermost",
            visibility="global",
        )
        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.mattermost.lab")
        self.assertEqual(create_kwargs["value"]["url"], "http://localhost:8065")
        self.assertEqual(create_kwargs["value"]["credential_id"], 7)
        self.assertNotIn("credential_id", result)
        self.assertNotIn("token", result)

    def test_create_source_conflict_raises_without_creating_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.mattermost.lab", {})
        with self.assertRaises(MattermostSourceConflictError):
            self.service.create_source(source_id="lab", url="http://x", token="tok")
        self.mock_credentials.create_credential.assert_not_called()

    def test_create_source_rejects_http_outside_development(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with patch(
            "services.mattermost.source_config_service.settings",
            SimpleNamespace(environment="production"),
        ):
            with self.assertRaises(UnsafeURLError):
                self.service.create_source(
                    source_id="lab", url="http://mattermost.example.com", token="tok"
                )
        self.mock_credentials.create_credential.assert_not_called()

    def test_create_source_allows_http_in_development(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_credentials.create_credential.return_value = {
            "id": 7,
            "username": "mattermost-bot",
        }
        self.mock_settings.create.return_value = _setting(
            "sources.mattermost.lab",
            {"url": "http://localhost:8065", "credential_id": 7},
        )
        with patch(
            "services.mattermost.source_config_service.settings",
            SimpleNamespace(environment="development"),
        ):
            self.service.create_source(
                source_id="lab", url="http://localhost:8065", token="tok"
            )
        self.mock_credentials.create_credential.assert_called_once()

    def test_create_source_allows_https_outside_development(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_credentials.create_credential.return_value = {
            "id": 7,
            "username": "mattermost-bot",
        }
        self.mock_settings.create.return_value = _setting(
            "sources.mattermost.lab",
            {"url": "https://mattermost.example.com", "credential_id": 7},
        )
        with patch(
            "services.mattermost.source_config_service.settings",
            SimpleNamespace(environment="production"),
        ):
            self.service.create_source(
                source_id="lab", url="https://mattermost.example.com", token="tok"
            )
        self.mock_credentials.create_credential.assert_called_once()

    def test_update_source_blank_token_keeps_existing_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab",
            {
                "url": "http://localhost:8065",
                "verify_ssl": True,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )
        self.mock_settings.update.return_value = _setting(
            "sources.mattermost.lab",
            {
                "url": "http://localhost:9000",
                "verify_ssl": True,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )

        result = self.service.update_source("lab", url="http://localhost:9000")

        self.mock_credentials.update_credential.assert_not_called()
        self.assertEqual(result["url"], "http://localhost:9000")

    def test_update_source_with_token_updates_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab",
            {
                "url": "http://localhost:8065",
                "verify_ssl": True,
                "timeout": 30.0,
                "credential_id": 7,
            },
        )
        self.mock_settings.update.return_value = _setting(
            "sources.mattermost.lab", {"credential_id": 7}
        )

        self.service.update_source("lab", token="new-token")

        self.mock_credentials.update_credential.assert_called_once_with(
            7, password="new-token"
        )

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(MattermostSourceNotFoundError):
            self.service.update_source("missing", url="http://x")

    def test_delete_source_removes_setting_and_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"credential_id": 7}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()
        self.mock_credentials.delete_credential.assert_called_once_with(7)

    def test_resolve_credentials_returns_decrypted_token(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab",
            {
                "url": "http://localhost:8065",
                "verify_ssl": True,
                "timeout": 15.0,
                "credential_id": 7,
            },
        )
        self.mock_credentials.get_credential_by_id.return_value = {
            "id": 7,
            "username": "mattermost-bot",
        }
        self.mock_credentials.get_decrypted_password.return_value = "s3cr3t-token"

        creds = self.service.resolve_credentials("lab")

        self.assertEqual(creds.base_url, "http://localhost:8065")
        self.assertEqual(creds.token, "s3cr3t-token")
        self.assertTrue(creds.verify_ssl)
        self.assertEqual(creds.timeout, 15.0)

    def test_list_sources_hides_credential_id(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.mattermost.lab", {"url": "http://x", "credential_id": 7}),
        ]
        result = self.service.list_sources()
        self.assertNotIn("credential_id", result[0])


if __name__ == "__main__":
    unittest.main()
