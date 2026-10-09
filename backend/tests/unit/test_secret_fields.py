"""Tests for services/workflow_context/secret_fields.py."""

from __future__ import annotations

import unittest

from core.crypto import EncryptionService
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    contains_sealed_secret,
    is_sealed_secret,
    path_is_known_secret,
    redact_secrets_in_data,
    register_secret_value,
    run_secret_scope,
    scrub_known_secrets,
    seal_secret,
    secret_is_present,
    unwrap_all_secrets,
    unwrap_secret,
    with_run_secret_scope,
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


class RunSecretScopeTests(unittest.TestCase):
    """W6: cleartext secrets that crossed an unwrap boundary are scrubbed from free text."""

    def test_known_secret_scrubbed_from_free_text(self) -> None:
        sealed = seal_secret("tacacs-key-12345", encryption=_ENC)
        with run_secret_scope():
            cleartext = unwrap_secret(sealed, encryption=_ENC)
            redacted = redact_secrets_in_data(
                {"msg": f"key={cleartext}!", "nested": [{"line": f"x {cleartext} y"}]}
            )
        self.assertEqual(redacted["msg"], "key=***REDACTED***!")
        self.assertEqual(redacted["nested"][0]["line"], "x ***REDACTED*** y")

    def test_short_values_are_not_tracked(self) -> None:
        with run_secret_scope():
            unwrap_secret("short", encryption=_ENC)
            register_secret_value("1234567")
            redacted = redact_secrets_in_data({"msg": "short and 1234567"})
        self.assertEqual(redacted["msg"], "short and 1234567")

    def test_no_scrub_outside_scope(self) -> None:
        unwrap_secret("tacacs-key-12345")
        self.assertEqual(
            redact_secrets_in_data({"msg": "tacacs-key-12345"}), {"msg": "tacacs-key-12345"}
        )

    def test_scope_ends_with_the_block(self) -> None:
        with run_secret_scope():
            register_secret_value("tacacs-key-12345")
        self.assertEqual(
            redact_secrets_in_data({"msg": "tacacs-key-12345"}), {"msg": "tacacs-key-12345"}
        )

    def test_longest_secret_replaced_first(self) -> None:
        with run_secret_scope():
            register_secret_value("abcdefgh")
            register_secret_value("abcdefgh-longer")
            redacted = redact_secrets_in_data({"msg": "abcdefgh-longer"})
        self.assertEqual(redacted["msg"], "***REDACTED***")

    def test_overlapping_secrets_leave_no_tail(self) -> None:
        with run_secret_scope():
            register_secret_value("abcdefgh")
            register_secret_value("defghijk")
            redacted = redact_secrets_in_data({"msg": "x abcdefghijk y"})
        self.assertEqual(redacted["msg"], "x ***REDACTED*** y")

    def test_repeated_and_adjacent_occurrences_are_all_scrubbed(self) -> None:
        with run_secret_scope():
            register_secret_value("secretvalue")
            redacted = redact_secrets_in_data({"msg": "secretvalue,secretvaluesecretvalue-end"})
        self.assertEqual(redacted["msg"], "***REDACTED***,***REDACTED***-end")

    def test_nested_scope_joins_the_outer_registry(self) -> None:
        with run_secret_scope():
            with run_secret_scope():
                register_secret_value("abcdefgh")
            redacted = redact_secrets_in_data({"msg": "abcdefgh"})
        self.assertEqual(redacted["msg"], "***REDACTED***")


class RunSecretScopeConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_is_shared_with_threads_and_gathered_tasks(self) -> None:
        import asyncio

        @with_run_secret_scope
        async def segment() -> dict:
            async def sibling() -> None:
                register_secret_value("from-task-1234")

            async def threaded() -> None:
                await asyncio.to_thread(register_secret_value, "from-thread-1234")

            await asyncio.gather(sibling(), threaded())
            return redact_secrets_in_data({"msg": "from-task-1234 / from-thread-1234"})

        result = await segment()
        self.assertEqual(result["msg"], "***REDACTED*** / ***REDACTED***")

    async def test_scrub_known_secrets_keeps_sealed_envelopes_usable(self) -> None:
        sealed = seal_secret("tacacs-key-12345", encryption=_ENC)

        @with_run_secret_scope
        async def segment() -> dict:
            register_secret_value("tacacs-key-12345")
            return scrub_known_secrets({"msg": "key tacacs-key-12345!", "bag": sealed})

        result = await segment()
        self.assertEqual(result["msg"], "key ***REDACTED***!")
        self.assertEqual(result["bag"], sealed)  # structure untouched: parent still merges it

    def test_scrub_known_secrets_is_a_noop_outside_a_scope(self) -> None:
        data = {"msg": "tacacs-key-12345"}
        self.assertIs(scrub_known_secrets(data), data)

    async def test_separate_segments_do_not_share_secrets(self) -> None:
        @with_run_secret_scope
        async def first() -> None:
            register_secret_value("segment-one-secret")

        @with_run_secret_scope
        async def second() -> dict:
            return redact_secrets_in_data({"msg": "segment-one-secret"})

        await first()
        self.assertEqual((await second())["msg"], "segment-one-secret")


if __name__ == "__main__":
    unittest.main()


class ContainsSealedSecretTests(unittest.TestCase):
    def test_finds_envelope_in_nested_dict_and_list(self) -> None:
        sealed = seal_secret("x", encryption=_ENC)
        self.assertTrue(contains_sealed_secret(sealed))
        self.assertTrue(contains_sealed_secret({"a": {"b": [1, {"c": sealed}]}}))

    def test_false_for_plain_data(self) -> None:
        self.assertFalse(contains_sealed_secret({"a": [1, "two", None], "b": {"c": "d"}}))
        self.assertFalse(contains_sealed_secret(None))
        self.assertFalse(contains_sealed_secret("plain"))


class UnwrapAllSecretsTests(unittest.TestCase):
    def test_replaces_envelopes_at_the_same_places(self) -> None:
        data = {
            "a": seal_secret("one", encryption=_ENC),
            "b": [
                seal_secret("two", encryption=_ENC),
                {"c": seal_secret("three", encryption=_ENC)},
            ],
            "d": "plain",
        }

        result = unwrap_all_secrets(data, encryption=_ENC)

        self.assertEqual(result, {"a": "one", "b": ["two", {"c": "three"}], "d": "plain"})

    def test_does_not_mutate_input(self) -> None:
        sealed = seal_secret("one", encryption=_ENC)
        data = {"a": sealed}
        unwrap_all_secrets(data, encryption=_ENC)
        self.assertEqual(data["a"], sealed)

    def test_undecryptable_envelope_raises(self) -> None:
        sealed = seal_secret("one", encryption=_ENC)
        other = EncryptionService("a-completely-different-key")
        with self.assertRaises(ValueError):
            unwrap_all_secrets({"a": sealed}, encryption=other)
