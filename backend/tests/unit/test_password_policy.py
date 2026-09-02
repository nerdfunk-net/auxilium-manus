from __future__ import annotations

import unittest

from services.auth.password_policy import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PasswordPolicyError,
    validate_password,
)


class TestValidatePassword(unittest.TestCase):
    def test_rejects_too_short(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("x" * (PASSWORD_MIN_LENGTH - 1))

    def test_accepts_minimum_length(self) -> None:
        validate_password("x" * PASSWORD_MIN_LENGTH)

    def test_rejects_too_long(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("x" * (PASSWORD_MAX_LENGTH + 1))

    def test_accepts_maximum_length(self) -> None:
        validate_password("x" * PASSWORD_MAX_LENGTH)

    def test_rejects_denylisted_password(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("changeme123")

    def test_denylist_check_is_case_insensitive(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("ChangeMe123")

    def test_rejects_password_equal_to_username(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("someusername", username="someusername")

    def test_username_check_is_case_insensitive(self) -> None:
        with self.assertRaises(PasswordPolicyError):
            validate_password("SomeUserName", username="someusername")

    def test_accepts_valid_password(self) -> None:
        validate_password("correct-horse-battery-staple", username="admin")

    def test_username_none_does_not_raise_on_unrelated_password(self) -> None:
        validate_password("correct-horse-battery-staple", username=None)


if __name__ == "__main__":
    unittest.main()
