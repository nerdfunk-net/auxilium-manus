"""Tests for AciSourceConfigService (mocked repository/credential layers)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.aci.common.exceptions import AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import (
    AciSourceConfigService,
    AciSourceConflictError,
    AciSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

KEY = "sources.aci.lab"
_GLOBAL_CRED = {"id": 7, "name": "aci-cred", "username": "admin", "visibility": "global"}


def _setting(value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=KEY, value=value, description=None)


class AciSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        module = "services.settings.source_config_base"
        patchers = {
            "settings": patch(f"{module}.SettingsRepository"),
            "credentials": patch(f"{module}.CredentialsService"),
            "validate": patch(
                f"{module}.validate_source_transport",
                side_effect=lambda url, *, verify_ssl=True, resolve_dns=True: (url or "").rstrip(
                    "/"
                ),
            ),
            "assert_global": patch(f"{module}.assert_global_credential"),
            "resolve_secret": patch(f"{module}.resolve_global_secret"),
        }
        mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)
        self.settings = mocks["settings"].return_value
        self.credentials = mocks["credentials"].return_value
        self.credentials.get_credential_by_id.return_value = {"id": 7, "name": "aci-cred"}
        self.assert_global = mocks["assert_global"]
        self.assert_global.return_value = dict(_GLOBAL_CRED)
        self.resolve_secret = mocks["resolve_secret"]
        self.resolve_secret.return_value = ("admin", "pw")
        self.service = AciSourceConfigService(db=MagicMock())

    def test_create_stores_credential_id_and_source_type(self) -> None:
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: _setting(value)

        result = self.service.create_source(
            source_id="lab",
            url="https://sandboxapicdc.cisco.com/",
            credential_id=7,
            verify_ssl=False,
        )

        kwargs = self.settings.create.call_args.kwargs
        self.assertEqual(kwargs["key"], KEY)
        self.assertEqual(kwargs["value"]["url"], "https://sandboxapicdc.cisco.com")
        self.assertEqual(kwargs["value"]["credential_id"], 7)
        self.assertEqual(kwargs["value"]["source_type"], "aci")
        self.assertFalse(kwargs["value"]["verify_ssl"])
        self.assertEqual(result["credential_name"], "aci-cred")
        self.assertEqual(kwargs["description"], "Cisco ACI source lab")

    def test_the_password_is_never_stored_on_the_source(self) -> None:
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: _setting(value)
        self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        stored = self.settings.create.call_args.kwargs["value"]
        self.assertNotIn("pw", str(stored))
        self.assertFalse({"password", "username", "secret"} & set(stored))

    def test_verify_ssl_defaults_to_true(self) -> None:
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: _setting(value)
        self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.assertTrue(self.settings.create.call_args.kwargs["value"]["verify_ssl"])

    def test_create_conflict(self) -> None:
        self.settings.get_by_key.return_value = _setting({})
        with self.assertRaises(AciSourceConflictError):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.assert_global.assert_not_called()

    def test_create_rejects_credential_without_username(self) -> None:
        self.settings.get_by_key.return_value = None
        self.assert_global.return_value = {"id": 7, "name": "x", "visibility": "global"}
        with self.assertRaises(AciValidationError):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)

    def test_create_rejects_an_unusable_credential(self) -> None:
        self.settings.get_by_key.return_value = None
        self.assert_global.side_effect = SourceCredentialError("private credential")
        with self.assertRaises(AciValidationError):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.settings.create.assert_not_called()

    def test_source_type_selects_the_aci_credential_rules(self) -> None:
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: _setting(value)
        self.service.create_source(source_id="lab", url="https://x", credential_id=7)
        self.assertEqual(self.assert_global.call_args.kwargs["source_type"], "aci")

    def test_resolve_credentials_builds_aci_credentials(self) -> None:
        self.settings.get_by_key.return_value = _setting(
            {"url": "https://10.10.20.14", "verify_ssl": False, "timeout": 12, "credential_id": 7}
        )
        creds = self.service.resolve_credentials("lab")
        self.assertEqual(
            creds,
            AciCredentials(
                base_url="https://10.10.20.14",
                username="admin",
                password="pw",
                timeout=12.0,
                verify_ssl=False,
            ),
        )

    def test_resolve_credentials_unknown_source(self) -> None:
        self.settings.get_by_key.return_value = None
        with self.assertRaises(AciSourceNotFoundError):
            self.service.resolve_credentials("nope")

    def test_resolve_credentials_without_linked_credential(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://x"})
        with self.assertRaises(AciValidationError):
            self.service.resolve_credentials("lab")

    def test_resolve_inline_credentials(self) -> None:
        creds = self.service.resolve_inline_credentials(
            url="https://10.10.20.14/", credential_id=7, verify_ssl=True, timeout=5
        )
        self.assertEqual(creds.base_url, "https://10.10.20.14")
        self.assertEqual((creds.username, creds.password, creds.timeout), ("admin", "pw", 5.0))

    def test_resolve_rejects_a_secret_without_username(self) -> None:
        self.resolve_secret.return_value = (None, "pw")
        with self.assertRaises(AciValidationError):
            self.service.resolve_inline_credentials(
                url="https://x", credential_id=7, verify_ssl=True, timeout=5
            )

    def test_messages_name_the_source_type(self) -> None:
        self.assertIn("Cisco ACI", str(AciSourceNotFoundError("lab")))
        self.assertIn("Cisco ACI", str(AciSourceConflictError("lab")))


if __name__ == "__main__":
    unittest.main()
