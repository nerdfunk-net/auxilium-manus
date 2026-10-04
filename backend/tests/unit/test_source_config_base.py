"""CredentialedHttpSourceService / SourceConfigStore: the behaviour shared by every source."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from services.credentials.source_credentials import SourceCredentialError
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)
from services.settings.source_keys import source_key_prefix

BASE = "services.settings.source_config_base"


class DummyValidationError(Exception):
    pass


class DummyNotFound(SourceNotFoundError):
    display_name = "Dummy"


class DummyConflict(SourceConflictError):
    display_name = "Dummy"


@dataclass(frozen=True)
class DummyCredentials:
    base_url: str
    username: str | None
    secret: str
    timeout: float
    verify_ssl: bool


class DummyService(CredentialedHttpSourceService[DummyCredentials]):
    source_type = "ise"
    display_name = "Dummy"
    description_label = "Dummy source"
    not_found_error = DummyNotFound
    conflict_error = DummyConflict
    validation_error = DummyValidationError

    def _build_credentials(self, *, base_url, username, secret, timeout, verify_ssl):
        return DummyCredentials(base_url, username, secret, timeout, verify_ssl)


class UsernameRequiredService(DummyService):
    requires_username = True


class UnverifiedByDefaultService(DummyService):
    default_verify_ssl = False


def _setting(value: dict) -> SimpleNamespace:
    return SimpleNamespace(key="sources.ise.x", value=value, description=None)


class SourceConfigBaseTests(unittest.TestCase):
    service_cls = DummyService

    def setUp(self) -> None:
        patchers = {
            "settings": patch(f"{BASE}.SettingsRepository"),
            "credentials": patch(f"{BASE}.CredentialsService"),
            "assert_global": patch(f"{BASE}.assert_global_credential"),
            "resolve_secret": patch(f"{BASE}.resolve_global_secret"),
            "validate": patch(
                f"{BASE}.validate_source_transport",
                side_effect=lambda url, *, verify_ssl, resolve_dns=True: url.rstrip("/"),
            ),
        }
        mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)
        self.settings = mocks["settings"].return_value
        self.credentials = mocks["credentials"].return_value
        self.assert_global = mocks["assert_global"]
        self.assert_global.return_value = {"id": 7, "username": "admin"}
        self.resolve_secret = mocks["resolve_secret"]
        self.resolve_secret.return_value = ("admin", "pw")
        self.validate = mocks["validate"]
        self.settings.get_by_key.return_value = None
        self.settings.create.side_effect = lambda key, value, description: SimpleNamespace(
            key=key, value=value, description=description
        )
        self.service = self.service_cls(db=object())


class CreateSourceTests(SourceConfigBaseTests):
    def test_stores_the_connection_fields_and_source_identity(self) -> None:
        self.credentials.get_credential_by_id.return_value = {"name": "vault"}

        result = self.service.create_source(
            source_id="lab", url="https://x.example.com/", credential_id=7, timeout=12.0
        )

        kwargs = self.settings.create.call_args.kwargs
        self.assertEqual(kwargs["key"], "sources.ise.lab")
        self.assertEqual(kwargs["description"], "Dummy source lab")
        self.assertEqual(
            kwargs["value"],
            {
                "url": "https://x.example.com",
                "verify_ssl": True,
                "timeout": 12.0,
                "credential_id": 7,
                "source_id": "lab",
                "source_type": "ise",
            },
        )
        self.assertEqual(result["credential_name"], "vault")
        self.assert_global.assert_called_once()
        self.assertEqual(self.assert_global.call_args.kwargs["source_type"], "ise")

    def test_conflict_is_raised_before_anything_is_validated(self) -> None:
        self.settings.get_by_key.return_value = _setting({})

        with self.assertRaisesRegex(DummyConflict, "Dummy source 'lab' already exists"):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)

        self.validate.assert_not_called()
        self.assert_global.assert_not_called()

    def test_wraps_credential_errors_into_the_validation_error(self) -> None:
        self.assert_global.side_effect = SourceCredentialError("wrong type")

        with self.assertRaisesRegex(DummyValidationError, "wrong type"):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)

        self.settings.create.assert_not_called()

    def test_verify_ssl_is_validated_and_stored(self) -> None:
        self.service.create_source(
            source_id="lab", url="https://x", credential_id=7, verify_ssl=False
        )

        self.validate.assert_called_once_with("https://x", verify_ssl=False, resolve_dns=True)
        self.assertFalse(self.settings.create.call_args.kwargs["value"]["verify_ssl"])


class DefaultVerifySslTests(SourceConfigBaseTests):
    service_cls = UnverifiedByDefaultService

    def test_create_uses_the_class_default_when_unset(self) -> None:
        self.service.create_source(source_id="lab", url="https://x", credential_id=7)

        self.assertFalse(self.settings.create.call_args.kwargs["value"]["verify_ssl"])

    def test_resolve_falls_back_to_the_class_default(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://x", "credential_id": 7})

        creds = self.service.resolve_credentials("x")

        self.assertFalse(creds.verify_ssl)


class UsernameRequiredTests(SourceConfigBaseTests):
    service_cls = UsernameRequiredService

    def test_create_requires_a_username(self) -> None:
        self.assert_global.return_value = {"id": 7, "username": ""}

        with self.assertRaisesRegex(
            DummyValidationError,
            "Selected credential has no username; Dummy requires a username \\+ secret.",
        ):
            self.service.create_source(source_id="lab", url="https://x", credential_id=7)

    def test_resolve_requires_a_username(self) -> None:
        self.resolve_secret.return_value = (None, "pw")
        self.settings.get_by_key.return_value = _setting({"url": "https://x", "credential_id": 7})

        with self.assertRaisesRegex(DummyValidationError, "no username"):
            self.service.resolve_credentials("x")


class UpdateSourceTests(SourceConfigBaseTests):
    def _existing(self, **value) -> None:
        stored = {"url": "https://old", "verify_ssl": True, "timeout": 30.0, "credential_id": 7}
        self.settings.get_by_key.return_value = _setting({**stored, **value})
        self.settings.update.side_effect = lambda setting, fields: _setting(fields["value"])

    def test_only_given_fields_change(self) -> None:
        self._existing()

        result = self.service.update_source("x", timeout=5.0)

        self.assertEqual(result["timeout"], 5.0)
        self.assertEqual(result["url"], "https://old")
        self.validate.assert_not_called()

    def test_verify_ssl_change_revalidates_the_stored_url(self) -> None:
        self._existing()

        self.service.update_source("x", verify_ssl=False)

        self.validate.assert_called_once_with("https://old", verify_ssl=False, resolve_dns=True)

    def test_new_url_is_validated_against_the_stored_verify_ssl(self) -> None:
        self._existing(verify_ssl=False)

        self.service.update_source("x", url="https://new/")

        self.validate.assert_called_once_with("https://new/", verify_ssl=False, resolve_dns=True)

    def test_new_credential_is_checked_and_stored(self) -> None:
        self._existing()

        result = self.service.update_source("x", credential_id=12)

        self.assertEqual(result["credential_id"], 12)
        self.assertEqual(self.assert_global.call_args.args[1], 12)

    def test_missing_source_is_not_found(self) -> None:
        self.settings.get_by_key.return_value = None

        with self.assertRaisesRegex(DummyNotFound, "Dummy source 'x' not found"):
            self.service.update_source("x", timeout=1.0)


class ResolveTests(SourceConfigBaseTests):
    def test_overrides_layer_on_top_of_the_stored_row(self) -> None:
        self.settings.get_by_key.return_value = _setting(
            {"url": "https://old", "verify_ssl": True, "timeout": 30.0, "credential_id": 7}
        )

        creds = self.service.resolve_credentials(
            "x", url="https://new", verify_ssl=False, timeout=9.0, credential_id=12
        )

        self.assertEqual(creds, DummyCredentials("https://new", "admin", "pw", 9.0, False))
        self.validate.assert_called_once_with("https://new", verify_ssl=False, resolve_dns=True)
        self.assertEqual(self.resolve_secret.call_args.args[1], 12)

    def test_stored_url_is_not_revalidated_without_an_override(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "http://old", "credential_id": 7})

        creds = self.service.resolve_credentials("x")

        self.assertEqual(creds.base_url, "http://old")
        self.validate.assert_not_called()

    def test_missing_credential_link_is_a_validation_error(self) -> None:
        self.settings.get_by_key.return_value = _setting({"url": "https://x"})

        with self.assertRaisesRegex(
            DummyValidationError, "Dummy source 'x' has no linked credential"
        ):
            self.service.resolve_credentials("x")

    def test_inline_credentials_do_not_touch_settings(self) -> None:
        creds = self.service.resolve_inline_credentials(
            url="https://x/", credential_id=7, verify_ssl=False, timeout=4
        )

        self.assertEqual(creds, DummyCredentials("https://x", "admin", "pw", 4.0, False))
        self.settings.get_by_key.assert_not_called()

    def test_secret_errors_are_wrapped(self) -> None:
        self.resolve_secret.side_effect = SourceCredentialError("no secret")

        with self.assertRaisesRegex(DummyValidationError, "no secret"):
            self.service.resolve_inline_credentials(
                url="https://x", credential_id=7, verify_ssl=True, timeout=1
            )


class StoreTests(SourceConfigBaseTests):
    def test_list_uses_the_type_prefix_and_adds_credential_names(self) -> None:
        self.settings.list_all.return_value = [_setting({"credential_id": 7})]
        self.credentials.get_credential_by_id.return_value = {"name": "vault"}

        result = self.service.list_sources()

        self.settings.list_all.assert_called_once_with(key_prefix="sources.ise.")
        self.assertEqual(result[0]["credential_name"], "vault")

    def test_get_and_delete_raise_not_found_with_the_display_name(self) -> None:
        self.settings.get_by_key.return_value = None

        with self.assertRaisesRegex(DummyNotFound, "Dummy source 'x' not found"):
            self.service.get_source("x")
        with self.assertRaises(DummyNotFound):
            self.service.delete_source("x")

    def test_delete_removes_only_the_setting(self) -> None:
        setting = _setting({"credential_id": 7})
        self.settings.get_by_key.return_value = setting

        self.service.delete_source("x")

        self.settings.delete.assert_called_once_with(setting)
        self.credentials.delete_credential.assert_not_called()

    def test_missing_credential_has_no_name(self) -> None:
        self.credentials.get_credential_by_id.return_value = None
        self.assertIsNone(self.service._to_public({"credential_id": 99})["credential_name"])
        self.assertIsNone(self.service._to_public({})["credential_name"])

    def test_source_key_prefix(self) -> None:
        self.assertEqual(source_key_prefix("catalyst_center"), "sources.catalyst_center.")


if __name__ == "__main__":
    unittest.main()
