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

PW = "test-passphrase-12"


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
        token = encrypt_with_passphrase("x", PW)
        parts = token.split(".")
        self.assertEqual(parts[0], "AM2")
        self.assertEqual(parts[1], DEFAULT_ALGORITHM)
        self.assertEqual(len(parts), 6)
        self.assertEqual(int(parts[2]), 1000)  # iteration count (lowered for the suite)
        self.assertEqual(algorithm_of_token(token), DEFAULT_ALGORITHM)

    def test_distinct_tokens_for_same_input(self) -> None:
        a = encrypt_with_passphrase("same", PW)
        b = encrypt_with_passphrase("same", PW)
        self.assertNotEqual(a, b)  # random salt + nonce
        self.assertEqual(decrypt_with_passphrase(a, PW), "same")
        self.assertEqual(decrypt_with_passphrase(b, PW), "same")

    def test_unicode_plaintext(self) -> None:
        token = encrypt_with_passphrase("pässwörd–✓", "clé partagée")
        self.assertEqual(decrypt_with_passphrase(token, "clé partagée"), "pässwörd–✓")


class FailureModeTests(unittest.TestCase):
    def test_wrong_passphrase_raises(self) -> None:
        token = encrypt_with_passphrase("secret", "right-passphrase-1")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(token, "wrong-passphrase-1")

    def test_tampered_ciphertext_raises(self) -> None:
        token = encrypt_with_passphrase("secret", PW)
        head, tail = token.rsplit(".", 1)
        flipped = "A" if tail[0] != "A" else "B"
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(f"{head}.{flipped}{tail[1:]}", PW)

    def test_malformed_token_raises(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase("not-a-token", PW)
        with self.assertRaises(PassphraseCipherError):
            algorithm_of_token("still-not-a-token")

    def test_algorithm_cross_check_mismatch_raises(self) -> None:
        token = encrypt_with_passphrase("secret", PW)
        tampered = token.replace("aes-256-gcm", "AM2x-unknown")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(tampered, PW, algorithm="aes-256-gcm")

    def test_empty_passphrase_rejected(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            encrypt_with_passphrase("x", "")
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(encrypt_with_passphrase("x", PW), "")


class Am2FormatTests(unittest.TestCase):
    def test_am1_token_rejected_with_clear_message(self) -> None:
        legacy = "AM1.aes-256-gcm.c2FsdA.bm9uY2U.Y3Q"
        with self.assertRaisesRegex(PassphraseCipherError, "older version"):
            decrypt_with_passphrase(legacy, PW)

    def test_iteration_count_is_authenticated_by_the_key(self) -> None:
        parts = encrypt_with_passphrase("secret", PW).split(".")
        parts[2] = "2000"
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(".".join(parts), PW)

    def test_short_passphrase_rejected_on_encrypt_and_decrypt(self) -> None:
        with self.assertRaises(PassphraseCipherError):
            encrypt_with_passphrase("x", "short")
        token = encrypt_with_passphrase("x", PW)
        with self.assertRaises(PassphraseCipherError):
            decrypt_with_passphrase(token, "short")

    def test_hostile_iteration_count_returns_fast(self) -> None:
        import time

        parts = encrypt_with_passphrase("secret", PW).split(".")
        for hostile in ("999999999", "10", "-5", "abc"):
            parts[2] = hostile
            start = time.perf_counter()
            with self.assertRaises(PassphraseCipherError):
                decrypt_with_passphrase(".".join(parts), PW)
            self.assertLess(time.perf_counter() - start, 0.5)

    def test_shared_salt_reuses_one_derivation(self) -> None:
        from unittest.mock import patch

        import core.passphrase_cipher as cipher

        cipher._derive_key.cache_clear()
        salt = b"s" * 16
        with patch.object(cipher, "PBKDF2HMAC", wraps=cipher.PBKDF2HMAC) as spy:
            tokens = [encrypt_with_passphrase(f"v{i}", PW, salt=salt) for i in range(5)]
            for i, token in enumerate(tokens):
                self.assertEqual(decrypt_with_passphrase(token, PW), f"v{i}")
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len({t.split(".")[4] for t in tokens}), 5)  # distinct nonces


if __name__ == "__main__":
    unittest.main()
