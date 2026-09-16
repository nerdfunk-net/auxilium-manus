"""Tests for services/secret_manager/policy.py."""

from __future__ import annotations

import unittest

from services.secret_manager.policy import (
    MAX_LENGTH,
    MIN_LENGTH,
    SecretCharset,
    SecretGenerationPolicy,
    generate_secret,
)


class SecretGenerationPolicyTests(unittest.TestCase):
    def test_rejects_length_below_minimum(self) -> None:
        with self.assertRaises(ValueError):
            SecretGenerationPolicy(length=MIN_LENGTH - 1)

    def test_rejects_length_above_maximum(self) -> None:
        with self.assertRaises(ValueError):
            SecretGenerationPolicy(length=MAX_LENGTH + 1)

    def test_accepts_boundary_lengths(self) -> None:
        SecretGenerationPolicy(length=MIN_LENGTH)
        SecretGenerationPolicy(length=MAX_LENGTH)


class GenerateSecretTests(unittest.TestCase):
    def test_hex_charset_produces_exact_length_and_valid_hex(self) -> None:
        for length in (4, 5, 32, 33):
            policy = SecretGenerationPolicy(charset=SecretCharset.HEX, length=length)
            value = generate_secret(policy)
            self.assertEqual(len(value), length)
            int(value, 16)  # raises ValueError if not valid hex

    def test_alnum_charset_produces_exact_length_and_alphabet(self) -> None:
        value = generate_secret(SecretGenerationPolicy(charset=SecretCharset.ALNUM, length=40))
        self.assertEqual(len(value), 40)
        self.assertTrue(value.isalnum())

    def test_alnum_symbols_charset_produces_exact_length(self) -> None:
        value = generate_secret(
            SecretGenerationPolicy(charset=SecretCharset.ALNUM_SYMBOLS, length=40)
        )
        self.assertEqual(len(value), 40)

    def test_successive_calls_are_not_identical(self) -> None:
        policy = SecretGenerationPolicy(charset=SecretCharset.HEX, length=32)
        values = {generate_secret(policy) for _ in range(10)}
        self.assertEqual(len(values), 10)


if __name__ == "__main__":
    unittest.main()
