"""Tests for services/workflow_context/secret_fields.py."""

from __future__ import annotations

import unittest

from core.crypto import EncryptionService
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    is_sealed_secret,
    path_is_known_secret,
    redact_secrets_in_data,
    seal_secret,
    secret_is_present,
    unwrap_secret,
)

_ENC = EncryptionService("test-secret-key-for-workflow-context")


class SealUnwrapTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed, encryption=_ENC), "s3cr3t")

    def test_unwrap_legacy_cleartext_string(self) -> None:
        self.assertEqual(unwrap_secret("legacy-value"), "legacy-value")

    def test_unwrap_none(self) -> None:
        self.assertIsNone(unwrap_secret(None))

    def test_unwrap_with_wrong_key_raises(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        other = EncryptionService("a-completely-different-key")
        with self.assertRaises(ValueError):
            unwrap_secret(sealed, encryption=other)

    def test_secret_is_present_sealed(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        self.assertTrue(secret_is_present(sealed))

    def test_secret_is_present_legacy_cleartext(self) -> None:
        self.assertTrue(secret_is_present("legacy-value"))

    def test_secret_is_present_empty(self) -> None:
        self.assertFalse(secret_is_present(""))
        self.assertFalse(secret_is_present(None))
        self.assertFalse(secret_is_present("   "))

    def test_path_is_known_secret(self) -> None:
        self.assertTrue(path_is_known_secret("tacacs.shared_secret"))
        self.assertTrue(path_is_known_secret("ise.tacacsSettings.sharedSecret"))
        self.assertFalse(path_is_known_secret("custom.location"))


class RedactSecretsInDataTests(unittest.TestCase):
    def test_redacts_known_bag_path_sealed(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        data = {
            "devices": {
                "dev-1": {
                    "attribute_bags": {"tacacs": {"shared_secret": sealed}},
                }
            }
        }
        redacted = redact_secrets_in_data(data)
        self.assertEqual(
            redacted["devices"]["dev-1"]["attribute_bags"]["tacacs"]["shared_secret"],
            REDACTED_PLACEHOLDER,
        )

    def test_redacts_known_bag_path_legacy_cleartext(self) -> None:
        data = {
            "devices": {
                "dev-1": {
                    "attribute_bags": {"tacacs": {"shared_secret": "legacy-cleartext"}},
                }
            }
        }
        redacted = redact_secrets_in_data(data)
        self.assertEqual(
            redacted["devices"]["dev-1"]["attribute_bags"]["tacacs"]["shared_secret"],
            REDACTED_PLACEHOLDER,
        )

    def test_redacts_nested_ise_shared_secret(self) -> None:
        data = {
            "devices": {
                "dev-1": {
                    "attribute_bags": {
                        "ise": {"tacacsSettings": {"sharedSecret": "s3cr3t", "enableKeyWrap": True}}
                    },
                }
            }
        }
        redacted = redact_secrets_in_data(data)
        ise_bag = redacted["devices"]["dev-1"]["attribute_bags"]["ise"]
        self.assertEqual(ise_bag["tacacsSettings"]["sharedSecret"], REDACTED_PLACEHOLDER)
        self.assertTrue(ise_bag["tacacsSettings"]["enableKeyWrap"])

    def test_redacts_sealed_envelope_anywhere_generic_sweep(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        data = {"outcomes": {"success": {"some_field": sealed}}}
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted["outcomes"]["success"]["some_field"], REDACTED_PLACEHOLDER)

    def test_does_not_mutate_input(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        data = {"attribute_bags": {"tacacs": {"shared_secret": sealed}}}
        redact_secrets_in_data(data)
        self.assertEqual(data["attribute_bags"]["tacacs"]["shared_secret"], sealed)

    def test_leaves_non_secret_data_untouched(self) -> None:
        data = {"devices": {"dev-1": {"attribute_bags": {"nautobot": {"role": "switch"}}}}}
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted, data)

    def test_redacts_password_key_outside_bags(self) -> None:
        data = {"output": {"password": "clear", "hostname": "r1"}}
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted["output"]["password"], REDACTED_PLACEHOLDER)
        self.assertEqual(redacted["output"]["hostname"], "r1")

    def test_does_not_redact_non_string_secret_named_values(self) -> None:
        data = {"config": {"enableKeyWrap": True, "token_count": 3}}
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted, data)

    def test_redacts_dash_and_suffix_variants_of_secret_names(self) -> None:
        data = {
            "a": {"snmp-community": "public"},
            "b": {"api_key": "abc123"},
            "c": {"radius_password": "clear"},
        }
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted["a"]["snmp-community"], REDACTED_PLACEHOLDER)
        self.assertEqual(redacted["b"]["api_key"], REDACTED_PLACEHOLDER)
        self.assertEqual(redacted["c"]["radius_password"], REDACTED_PLACEHOLDER)


if __name__ == "__main__":
    unittest.main()
