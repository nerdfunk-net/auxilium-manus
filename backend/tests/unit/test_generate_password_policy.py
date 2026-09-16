"""Tests for workflow_steps/generate_password/password_policy.py."""

from __future__ import annotations

import unittest

from workflow_steps.generate_password.password_policy import (
    DIGITS,
    LOWERCASE,
    MAX_LENGTH,
    MIN_LENGTH,
    SPECIAL_CHARACTERS,
    UPPERCASE,
    PasswordPolicy,
    generate_password,
)


class PasswordPolicyTests(unittest.TestCase):
    def test_rejects_length_below_minimum(self) -> None:
        with self.assertRaises(ValueError):
            PasswordPolicy(length=MIN_LENGTH - 1, min_digits=MIN_LENGTH - 1)

    def test_rejects_length_above_maximum(self) -> None:
        with self.assertRaises(ValueError):
            PasswordPolicy(length=MAX_LENGTH + 1, min_digits=MAX_LENGTH + 1)

    def test_accepts_boundary_lengths(self) -> None:
        PasswordPolicy(
            length=MIN_LENGTH,
            min_digits=MIN_LENGTH,
            min_uppercase=0,
            min_lowercase=0,
            min_special=0,
        )
        PasswordPolicy(
            length=MAX_LENGTH,
            min_digits=MAX_LENGTH,
            min_uppercase=0,
            min_lowercase=0,
            min_special=0,
        )

    def test_rejects_minimums_summing_above_length(self) -> None:
        with self.assertRaises(ValueError):
            PasswordPolicy(length=8, min_digits=5, min_uppercase=5, min_lowercase=0, min_special=0)

    def test_rejects_all_minimums_zero(self) -> None:
        with self.assertRaises(ValueError):
            PasswordPolicy(length=16, min_digits=0, min_uppercase=0, min_lowercase=0, min_special=0)

    def test_accepts_single_nonzero_minimum(self) -> None:
        policy = PasswordPolicy(
            length=16, min_digits=1, min_uppercase=0, min_lowercase=0, min_special=0
        )
        self.assertEqual(policy.min_digits, 1)


class GeneratePasswordTests(unittest.TestCase):
    def test_produces_exact_length(self) -> None:
        for length, digits, upper, lower, special in (
            (8, 2, 2, 2, 2),
            (16, 2, 2, 2, 2),
            (32, 8, 8, 8, 8),
            (10, 10, 0, 0, 0),
        ):
            policy = PasswordPolicy(
                length=length,
                min_digits=digits,
                min_uppercase=upper,
                min_lowercase=lower,
                min_special=special,
            )
            self.assertEqual(len(generate_password(policy)), length)

    def test_honors_each_minimum_count(self) -> None:
        policy = PasswordPolicy(
            length=40, min_digits=10, min_uppercase=10, min_lowercase=10, min_special=10
        )
        for _ in range(20):
            value = generate_password(policy)
            self.assertGreaterEqual(sum(c in DIGITS for c in value), policy.min_digits)
            self.assertGreaterEqual(sum(c in UPPERCASE for c in value), policy.min_uppercase)
            self.assertGreaterEqual(sum(c in LOWERCASE for c in value), policy.min_lowercase)
            self.assertGreaterEqual(sum(c in SPECIAL_CHARACTERS for c in value), policy.min_special)

    def test_disabled_category_excluded_from_fill_pool(self) -> None:
        policy = PasswordPolicy(
            length=32, min_digits=32, min_uppercase=0, min_lowercase=0, min_special=0
        )
        for _ in range(50):
            value = generate_password(policy)
            self.assertTrue(all(c in DIGITS for c in value))

    def test_all_characters_come_from_known_alphabets(self) -> None:
        policy = PasswordPolicy(
            length=64, min_digits=16, min_uppercase=16, min_lowercase=16, min_special=16
        )
        alphabet = DIGITS + UPPERCASE + LOWERCASE + SPECIAL_CHARACTERS
        value = generate_password(policy)
        self.assertTrue(all(c in alphabet for c in value))

    def test_special_alphabet_matches_fixed_constant(self) -> None:
        policy = PasswordPolicy(
            length=32, min_digits=0, min_uppercase=0, min_lowercase=0, min_special=32
        )
        for _ in range(20):
            value = generate_password(policy)
            self.assertTrue(all(c in SPECIAL_CHARACTERS for c in value))

    def test_successive_calls_are_not_identical(self) -> None:
        policy = PasswordPolicy(
            length=16, min_digits=2, min_uppercase=2, min_lowercase=2, min_special=2
        )
        values = {generate_password(policy) for _ in range(10)}
        self.assertEqual(len(values), 10)


if __name__ == "__main__":
    unittest.main()
