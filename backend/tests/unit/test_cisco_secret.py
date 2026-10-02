"""Tests for core.cisco_secret (Cisco type 7/8/9 wrapper)."""

from __future__ import annotations

import unittest

from network_secret import cisco_type8, cisco_type9

from core.cisco_secret import (
    ALGORITHM_CISCO_TYPE7,
    ALGORITHM_CISCO_TYPE8,
    ALGORITHM_CISCO_TYPE9,
    CISCO_ALGORITHMS,
    CiscoSecretError,
    decrypt_cisco,
    encrypt_cisco,
    is_cisco_algorithm,
)


class CiscoSecretTests(unittest.TestCase):
    def test_is_cisco_algorithm(self) -> None:
        for algo in CISCO_ALGORITHMS:
            self.assertTrue(is_cisco_algorithm(algo))
        self.assertTrue(is_cisco_algorithm(" Cisco-Type7 "))
        self.assertFalse(is_cisco_algorithm("aes-256-gcm"))
        self.assertFalse(is_cisco_algorithm(None))
        self.assertFalse(is_cisco_algorithm(""))

    def test_type7_known_vector_decrypts(self) -> None:
        self.assertEqual(decrypt_cisco("060506324F41", ALGORITHM_CISCO_TYPE7), "cisco")

    def test_type7_round_trip(self) -> None:
        token = encrypt_cisco("TacacsKey!42", ALGORITHM_CISCO_TYPE7)
        self.assertRegex(token, r"^\d{2}[0-9A-F]+$")
        self.assertEqual(decrypt_cisco(token, ALGORITHM_CISCO_TYPE7), "TacacsKey!42")

    def test_type7_rejects_non_latin1(self) -> None:
        with self.assertRaises(CiscoSecretError) as ctx:
            encrypt_cisco("pässwörd✓", ALGORITHM_CISCO_TYPE7)
        self.assertNotIn("pässwörd", str(ctx.exception))

    def test_type7_malformed_token(self) -> None:
        with self.assertRaises(CiscoSecretError):
            decrypt_cisco("zz", ALGORITHM_CISCO_TYPE7)

    def test_type8_hash_format_and_check(self) -> None:
        value = encrypt_cisco("S3cretPass", ALGORITHM_CISCO_TYPE8)
        self.assertRegex(value, r"^\$8\$[^$ ]{14}\$[./0-9A-Za-z]{43}$")
        self.assertTrue(cisco_type8.check(value, "S3cretPass")[2])
        self.assertFalse(cisco_type8.check(value, "other")[2])

    def test_type9_hash_format_and_check(self) -> None:
        value = encrypt_cisco("S3cretPass", ALGORITHM_CISCO_TYPE9)
        self.assertRegex(value, r"^\$9\$[^$ ]{14}\$[./0-9A-Za-z]{43}$")
        self.assertTrue(cisco_type9.check(value, "S3cretPass")[2])

    def test_hashes_are_salted(self) -> None:
        self.assertNotEqual(
            encrypt_cisco("same", ALGORITHM_CISCO_TYPE8),
            encrypt_cisco("same", ALGORITHM_CISCO_TYPE8),
        )

    def test_one_way_hashes_cannot_be_decrypted(self) -> None:
        for algo in (ALGORITHM_CISCO_TYPE8, ALGORITHM_CISCO_TYPE9):
            with self.assertRaises(CiscoSecretError) as ctx:
                decrypt_cisco("$8$abc$def", algo)
            self.assertIn("one-way", str(ctx.exception))

    def test_unknown_algorithm(self) -> None:
        with self.assertRaises(CiscoSecretError):
            encrypt_cisco("x", "cisco-type5")
        with self.assertRaises(CiscoSecretError):
            decrypt_cisco("x", "aes-256-gcm")


if __name__ == "__main__":
    unittest.main()
