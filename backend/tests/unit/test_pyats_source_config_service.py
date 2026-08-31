"""Tests for PyATSSourceConfigService: keeps the settings row pointed at a
user-selected global vault credential (mocked repository/credential layers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.credentials.source_credentials import SourceCredentialError
from services.pyats.common.exceptions import PyATSValidationError
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
        assert_global_patcher = patch(
            "services.pyats.source_config_service.assert_global_credential"
        )
        resolve_secret_patcher = patch("services.pyats.source_config_service.resolve_global_secret")
        self.mock_settings_cls = settings_patcher.start()
        self.mock_credentials_cls = credentials_patcher.start()
        validate_patcher.start()
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
        self.mock_resolve_secret.return_value = ("pyats-shim", "s3cr3t-token")

        self.service = PyATSSourceConfigService(db=MagicMock())

    def test_create_source_stores_credential_id_no_credential_created(self) -> None:
        self.mock_settings.get_by_key.return_value = None
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
            credential_id=7,
        )

        self.mock_assert_global.assert_called_once()
        self.assertEqual(self.mock_assert_global.call_args.args[1], 7)
        self.mock_credentials.create_credential.assert_not_called()
        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.pyats.lab")
        self.assertEqual(create_kwargs["value"]["url"], "http://pyats-shim:8100")
        self.assertEqual(create_kwargs["value"]["credential_id"], 7)
        self.assertEqual(result["credential_id"], 7)
        self.assertEqual(result["credential_name"], "vault-tok")
        self.assertNotIn("token", result)

    def test_create_source_rejects_non_global_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_assert_global.side_effect = SourceCredentialError("not global")
        with self.assertRaises(SourceCredentialError):
            self.service.create_source(source_id="lab", url="http://x", credential_id=9)
        self.mock_settings.create.assert_not_called()

    def test_create_source_conflict_raises(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.pyats.lab", {})
        with self.assertRaises(PyATSSourceConflictError):
            self.service.create_source(source_id="lab", url="http://x", credential_id=7)
        self.mock_assert_global.assert_not_called()

    def test_update_source_without_credential_id_keeps_existing(self) -> None:
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

        self.mock_assert_global.assert_not_called()
        updated_value = self.mock_settings.update.call_args.args[1]["value"]
        self.assertEqual(updated_value["credential_id"], 7)
        self.assertEqual(result["url"], "http://pyats-shim:9000")

    def test_update_source_with_new_credential_id_revalidates(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab", {"url": "http://x", "credential_id": 7}
        )
        self.mock_settings.update.return_value = _setting(
            "sources.pyats.lab", {"url": "http://x", "credential_id": 12}
        )

        self.service.update_source("lab", credential_id=12)

        self.mock_assert_global.assert_called_once()
        self.assertEqual(self.mock_assert_global.call_args.args[1], 12)
        updated_value = self.mock_settings.update.call_args.args[1]["value"]
        self.assertEqual(updated_value["credential_id"], 12)

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(PyATSSourceNotFoundError):
            self.service.update_source("missing", url="http://x")

    def test_delete_source_removes_setting_only(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab", {"credential_id": 7}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()
        self.mock_credentials.delete_credential.assert_not_called()

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

        creds = self.service.resolve_credentials("lab")

        self.assertEqual(creds.base_url, "http://pyats-shim:8100")
        self.assertEqual(creds.token, "s3cr3t-token")
        self.assertFalse(creds.verify_ssl)
        self.assertEqual(creds.timeout, 15.0)
        self.assertEqual(self.mock_resolve_secret.call_args.args[1], 7)

    def test_resolve_credentials_with_credential_id_override(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab",
            {
                "url": "http://pyats-shim:8100",
                "verify_ssl": False,
                "timeout": 15.0,
                "credential_id": 7,
            },
        )
        self.service.resolve_credentials("lab", credential_id=99)
        self.assertEqual(self.mock_resolve_secret.call_args.args[1], 99)

    def test_resolve_credentials_rejects_private_credential(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.pyats.lab", {"url": "http://x", "credential_id": 7}
        )
        self.mock_resolve_secret.side_effect = SourceCredentialError("private")
        with self.assertRaises(PyATSValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_inline_credentials_no_settings_lookup(self) -> None:
        creds = self.service.resolve_inline_credentials(
            url="http://pyats-shim:8100/", credential_id=7, verify_ssl=True, timeout=20.0
        )
        self.mock_settings.get_by_key.assert_not_called()
        self.assertEqual(creds.base_url, "http://pyats-shim:8100")
        self.assertEqual(creds.token, "s3cr3t-token")
        self.assertTrue(creds.verify_ssl)

    def test_list_sources_exposes_credential_id_and_name(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.pyats.lab", {"url": "http://x", "credential_id": 7}),
        ]
        result = self.service.list_sources()
        self.assertEqual(result[0]["credential_id"], 7)
        self.assertEqual(result[0]["credential_name"], "vault-tok")


if __name__ == "__main__":
    unittest.main()
