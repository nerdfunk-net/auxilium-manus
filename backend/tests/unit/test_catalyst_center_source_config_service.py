"""Tests for CatalystCenterSourceConfigService (mocked repository/credential layers)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.source_config_service import (
    CatalystCenterSourceConfigService,
    CatalystCenterSourceConflictError,
    CatalystCenterSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

KEY = "sources.catalyst_center.lab"
_GLOBAL_CRED = {"id": 7, "name": "cc-cred", "username": "admin", "visibility": "global"}


def _setting(value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=KEY, value=value, description=None)


class CatalystCenterSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        module = "services.catalyst_center.source_config_service"
        patchers = {
            "settings": patch(f"{module}.SettingsRepository"),
            "credentials": patch(f"{module}.CredentialsService"),
            "validate": patch(
                f"{module}.validate_outbound_http_url",
                side_effect=lambda url, resolve_dns=True: (url or "").rstrip("/"),
            ),
            "assert_global": patch(f"{module}.assert_global_credential"),
            "resolve_secret": patch(f"{module}.resolve_global_secret"),
        }
        mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)
        self.settings = mocks["settings"].return_value
        self.credentials = mocks["credentials"].return_value
        self.credentials.get_credential_by_id.return_value = {"id": 7, "name": "cc-cred"}
        self.assert_global = mocks["assert_global"]
        self.assert_global.return_value = dict(_GLOBAL_CRED)
        self.resolve_secret = mocks["resolve_secret"]
        self.resolve_secret.return_value = ("admin", "pw")
        self.service = CatalystCenterSourceConfigService(db=MagicMock())

    def test_create_stores_credential_id_and_source_type(self) -> None:
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: _setting(value)

        result = self.service.create_source(
            source_id="lab", url="https://10.10.20.85/", credential_id=7, verify_ssl=False
        )

        kwargs = self.settings.create.call_args.kwargs
        self.assertEqual(kwargs["key"], KEY)
        self.assertEqual(kwargs["value"]["url"], "https://10.10.20.85")
        self.assertEqual(kwargs["value"]["credential_id"], 7)
        self.assertEqual(kwargs["value"]["source_type"], "catalyst_center")
        self.assertFalse(kwargs["value"]["verify_ssl"])
        self.assertEqual(result["credential_name"], "cc-cred")
        self.credentials.create_credential.assert_not_called()

    def test_create_conflict(self) -> None:
        self.settings.get_by_key.return_value = _setting({})
        with self.assertRaises(CatalystCenterSourceConflictError):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.assert_global.assert_not_called()

    def test_create_rejects_credential_without_username(self) -> None:
        self.settings.get_by_key.return_value = None
        self.assert_global.return_value = {"id": 7, "name": "x", "visibility": "global"}
        with self.assertRaises(CatalystCenterValidationError):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.settings.create.assert_not_called()

    def test_create_rejects_bad_source_id(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_source(source_id="Bad Id", url="https://x", credential_id=7)

    def test_update_keeps_existing_credential_when_not_given(self) -> None:
        stored = {"url": "https://a", "verify_ssl": True, "timeout": 30.0, "credential_id": 7}
        self.settings.get_by_key.return_value = _setting(stored)
        self.settings.update.side_effect = lambda setting, fields: _setting(fields["value"])

        result = self.service.update_source("lab", url="https://b")

        self.assert_global.assert_not_called()
        self.assertEqual(result["url"], "https://b")
        self.assertEqual(result["credential_id"], 7)
        self.assertEqual(stored["url"], "https://a")  # stored value not mutated

    def test_update_revalidates_new_credential(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://a", "credential_id": 7})
        self.settings.update.side_effect = lambda setting, fields: _setting(fields["value"])
        self.service.update_source("lab", credential_id=12)
        self.assertEqual(self.assert_global.call_args.args[1], 12)

    def test_update_missing_raises_not_found(self) -> None:
        self.settings.get_by_key.return_value = None
        with self.assertRaises(CatalystCenterSourceNotFoundError):
            self.service.update_source("lab", url="https://x")

    def test_delete_removes_setting_only(self) -> None:
        self.settings.get_by_key.return_value = _setting({"credential_id": 7})
        self.service.delete_source("lab")
        self.settings.delete.assert_called_once()
        self.credentials.delete_credential.assert_not_called()

    def test_list_and_get_expose_credential_name(self) -> None:
        self.settings.list_all.return_value = [_setting({"url": "https://a", "credential_id": 7})]
        self.assertEqual(self.service.list_sources()[0]["credential_name"], "cc-cred")
        self.settings.get_by_key.return_value = _setting({"url": "https://a", "credential_id": 7})
        self.assertEqual(self.service.get_source("lab")["credential_id"], 7)

    def test_resolve_credentials_uses_vault_secret(self) -> None:
        self.settings.get_by_key.return_value = _setting(
            {"url": "https://10.10.20.85", "verify_ssl": False, "timeout": 12, "credential_id": 7}
        )
        creds = self.service.resolve_credentials("lab")
        self.assertEqual(
            (creds.base_url, creds.username, creds.password, creds.verify_ssl, creds.timeout),
            ("https://10.10.20.85", "admin", "pw", False, 12.0),
        )

    def test_resolve_credentials_overrides_layer_on_saved_values(self) -> None:
        self.settings.get_by_key.return_value = _setting(
            {"url": "https://a", "verify_ssl": True, "timeout": 30, "credential_id": 7}
        )
        creds = self.service.resolve_credentials("lab", verify_ssl=False, timeout=5)
        self.assertFalse(creds.verify_ssl)
        self.assertEqual(creds.timeout, 5.0)

    def test_resolve_credentials_without_linked_credential(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://a"})
        with self.assertRaises(CatalystCenterValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_wraps_credential_errors(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://a", "credential_id": 7})
        self.resolve_secret.side_effect = SourceCredentialError("private credential")
        with self.assertRaises(CatalystCenterValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_requires_username(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://a", "credential_id": 7})
        self.resolve_secret.return_value = (None, "pw")
        with self.assertRaises(CatalystCenterValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_inline_builds_unsaved_credentials(self) -> None:
        creds = self.service.resolve_inline_credentials(
            url="https://10.10.20.85/", credential_id=7, verify_ssl=True, timeout=20
        )
        self.settings.get_by_key.assert_not_called()
        self.assertEqual(
            (creds.base_url, creds.username, creds.timeout),
            ("https://10.10.20.85", "admin", 20.0),
        )
