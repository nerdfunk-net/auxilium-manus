"""Tests for MattermostSourceConfigService: keeps the settings row pointed at a
user-selected global vault credential (mocked repository/credential layers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.credentials.source_credentials import SourceCredentialError
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.source_config_service import (
    MattermostSourceConfigService,
    MattermostSourceConflictError,
    MattermostSourceNotFoundError,
)


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class MattermostSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.mattermost.source_config_service.SettingsRepository")
        credentials_patcher = patch("services.mattermost.source_config_service.CredentialsService")
        validate_patcher = patch(
            "services.mattermost.source_config_service.validate_source_transport",
            side_effect=lambda url, *, verify_ssl=True, resolve_dns=True: (url or "").rstrip("/"),
        )
        assert_global_patcher = patch(
            "services.mattermost.source_config_service.assert_global_credential"
        )
        resolve_secret_patcher = patch(
            "services.mattermost.source_config_service.resolve_global_secret"
        )
        self.mock_settings_cls = settings_patcher.start()
        self.mock_credentials_cls = credentials_patcher.start()
        self.mock_validate = validate_patcher.start()
        self.mock_assert_global = assert_global_patcher.start()
        self.mock_resolve_secret = resolve_secret_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.addCleanup(credentials_patcher.stop)
        self.addCleanup(validate_patcher.stop)
        self.addCleanup(assert_global_patcher.stop)
        self.addCleanup(resolve_secret_patcher.stop)

        self.mock_settings = self.mock_settings_cls.return_value
        self.mock_credentials = self.mock_credentials_cls.return_value
        self.mock_credentials.get_credential_by_id.return_value = {"id": 7, "name": "vault-tok"}
        self.mock_assert_global.return_value = {
            "id": 7,
            "name": "vault-tok",
            "visibility": "global",
        }
        self.mock_resolve_secret.return_value = ("mattermost-bot", "s3cr3t-token")

        self.service = MattermostSourceConfigService(db=MagicMock())

    def test_create_source_stores_credential_id_no_credential_created(self) -> None:
        self.mock_settings.get_by_key.return_value = None
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
            source_id="lab", url="http://localhost:8065/", credential_id=7
        )

        self.mock_assert_global.assert_called_once()
        self.assertEqual(self.mock_assert_global.call_args.args[1], 7)
        self.mock_credentials.create_credential.assert_not_called()
        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.mattermost.lab")
        self.assertEqual(create_kwargs["value"]["url"], "http://localhost:8065")
        self.assertEqual(create_kwargs["value"]["credential_id"], 7)
        self.assertEqual(result["credential_id"], 7)
        self.assertEqual(result["credential_name"], "vault-tok")

    def test_create_source_conflict_raises(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.mattermost.lab", {})
        with self.assertRaises(MattermostSourceConflictError):
            self.service.create_source(source_id="lab", url="http://x", credential_id=7)
        self.mock_assert_global.assert_not_called()

    def test_update_source_without_credential_id_keeps_existing(self) -> None:
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

        self.mock_assert_global.assert_not_called()
        self.assertEqual(result["url"], "http://localhost:9000")

    def test_update_source_with_new_credential_id_revalidates(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"url": "http://x", "credential_id": 7}
        )
        self.mock_settings.update.return_value = _setting(
            "sources.mattermost.lab", {"url": "http://x", "credential_id": 12}
        )

        self.service.update_source("lab", credential_id=12)

        self.mock_assert_global.assert_called_once()
        self.assertEqual(self.mock_assert_global.call_args.args[1], 12)

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(MattermostSourceNotFoundError):
            self.service.update_source("missing", url="http://x")

    def test_delete_source_removes_setting_only(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"credential_id": 7}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()
        self.mock_credentials.delete_credential.assert_not_called()

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

        creds = self.service.resolve_credentials("lab")

        self.assertEqual(creds.base_url, "http://localhost:8065")
        self.assertEqual(creds.token, "s3cr3t-token")
        self.assertTrue(creds.verify_ssl)
        self.assertEqual(creds.timeout, 15.0)

    def test_resolve_credentials_rejects_private_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"url": "http://x", "credential_id": 7}
        )
        self.mock_resolve_secret.side_effect = SourceCredentialError("private")
        with self.assertRaises(MattermostValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_inline_credentials_no_settings_lookup(self) -> None:
        creds = self.service.resolve_inline_credentials(
            url="http://localhost:8065/", credential_id=7, verify_ssl=True, timeout=20.0
        )
        self.mock_settings.get_by_key.assert_not_called()
        self.assertEqual(creds.base_url, "http://localhost:8065")
        self.assertEqual(creds.token, "s3cr3t-token")

    def test_list_sources_exposes_credential_id_and_name(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.mattermost.lab", {"url": "http://x", "credential_id": 7}),
        ]
        result = self.service.list_sources()
        self.assertEqual(result[0]["credential_id"], 7)
        self.assertEqual(result[0]["credential_name"], "vault-tok")

    def test_create_source_passes_verify_ssl_to_transport_policy(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.side_effect = lambda key, value, description: _setting(
            "sources.mattermost.lab", value
        )

        self.service.create_source(
            source_id="lab", url="https://x.example.com", credential_id=7, verify_ssl=False
        )

        self.mock_validate.assert_called_once_with(
            "https://x.example.com", verify_ssl=False, resolve_dns=True
        )

    def test_update_source_revalidates_url_when_only_verify_ssl_changes(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"url": "http://x", "verify_ssl": True, "credential_id": 7}
        )
        self.mock_settings.update.side_effect = lambda setting, fields: _setting(
            "sources.mattermost.lab", fields["value"]
        )

        self.service.update_source("lab", verify_ssl=False)

        self.mock_validate.assert_called_once_with("http://x", verify_ssl=False, resolve_dns=True)

    def test_update_source_validates_new_url_against_stored_verify_ssl(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"url": "https://old", "verify_ssl": True, "credential_id": 7}
        )
        self.mock_settings.update.side_effect = lambda setting, fields: _setting(
            "sources.mattermost.lab", fields["value"]
        )

        self.service.update_source("lab", url="https://new")

        self.mock_validate.assert_called_once_with("https://new", verify_ssl=True, resolve_dns=True)

    def test_update_source_without_url_or_verify_ssl_skips_transport_check(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.mattermost.lab", {"url": "http://x", "credential_id": 7}
        )
        self.mock_settings.update.side_effect = lambda setting, fields: _setting(
            "sources.mattermost.lab", fields["value"]
        )

        self.service.update_source("lab", timeout=5.0)

        self.mock_validate.assert_not_called()

    def test_create_source_binds_credential_to_the_source_type(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.side_effect = lambda key, value, description: _setting(
            "sources.mattermost.lab", value
        )

        self.service.create_source(source_id="lab", url="https://x.example.com", credential_id=7)

        self.assertEqual(self.mock_assert_global.call_args.kwargs["source_type"], "mattermost")

    def test_create_source_rejects_credential_of_wrong_type(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_assert_global.side_effect = SourceCredentialError("wrong type")

        with self.assertRaises(SourceCredentialError):
            self.service.create_source(
                source_id="lab", url="https://x.example.com", credential_id=9
            )

        self.mock_settings.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
