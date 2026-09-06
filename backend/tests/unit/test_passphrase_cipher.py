"""Tests for core.passphrase_cipher."""

from __future__ import annotations

import unittest

from core.passphrase_cipher import (
    DEFAULT_ALGORITHM,
    PassphraseCipherError,
    algorithm_of_token,
    decrypt_with_passphrase,
    encrypt_with_passphrase,
    normalize_algorithm,
)


class NormalizeAlgorithmTests(unittest.TestCase):
    def test_blank_and_none_default(self) -> None:
        self.assertEqual(normalize_algorithm(None), DEFAULT_ALGORITHM)
        self.assertEqual(normalize_algorithm(""), DEFAULT_ALGORITHM)
        self.assertEqual(normalize_algorithm("  "), DEFAULT_ALGORITHM)

    def test_known_algorithm_passes_through(self) -> None:
        self.assertEqual(normalize_algorithm("AES-256-GCM"), "aes-256-gcm")

    def test_unknown_algorithm_raises(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            normalize_algorithm("rot13")


class RoundTripTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        token = encrypt_with_passphrase("hunter2", "correct horse battery staple")
        self.assertEqual(
            decrypt_with_passphrase(token, "correct horse battery staple"), "hunter2"
        )

    def test_token_is_self_describing(self) -> None:
        token = encrypt_with_passphrase("x", "pw")
        parts = token.split(".")
        self.assertEqual(parts[0], "AM1")
        self.assertEqual(parts[1], DEFAULT_ALGORITHM)
        self.assertEqual(len(parts), 5)
        self.assertEqual(algorithm_of_token(token), DEFAULT_ALGORITHM)

    def test_distinct_tokens_for_same_input(self) -> None:
        a = encrypt_with_passphrase("same", "pw")
        b = encrypt_with_passphrase("same", "pw")
        self.assertNotEqual(a, b)  # random salt + nonce
        self.assertEqual(decrypt_with_passphrase(a, "pw"), "same")
        self.assertEqual(decrypt_with_passphrase(b, "pw"), "same")

    def test_unicode_plaintext(self) -> None:
        token = encrypt_with_passphrase("pässwörd–✓", "clé partagée")
        self.assertEqual(decrypt_with_passphrase(token, "clé partagée"), "pässwörd–✓")


class FailureModeTests(unittest.TestCase):
    def test_wrong_passphrase_raises(self) -> None:
        token = encrypt_with_passphrase("secret", "right")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(token, "wrong")

    def test_tampered_ciphertext_raises(self) -> None:
        token = encrypt_with_passphrase("secret", "pw")
        head, tail = token.rsplit(".", 1)
        flipped = "A" if tail[0] != "A" else "B"
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(f"{head}.{flipped}{tail[1:]}", "pw")

    def test_malformed_token_raises(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase("not-a-token", "pw")
        with self.assertRaises(PassphraseCipherError):
            algorithm_of_token("still-not-a-token")

    def test_algorithm_cross_check_mismatch_raises(self) -> None:
        token = encrypt_with_passphrase("secret", "pw")
        tampered = token.replace("aes-256-gcm", "AM1x-unknown")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(tampered, "pw", algorithm="aes-256-gcm")

    def test_empty_passphrase_rejected(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            encrypt_with_passphrase("x", "")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(encrypt_with_passphrase("x", "pw"), "")


if __name__ == "__main__":
    unittest.main()
