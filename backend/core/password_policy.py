"""Password acceptance rules (NIST SP 800-63B style: length, not composition)."""

from __future__ import annotations

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
_DENYLIST = frozenset({"password", "passw0rd", "admin", "changeme", "letmein", "welcome"})


class PasswordPolicyError(ValueError):
    """Raised with a user-facing message when a password is not acceptable."""


def validate_password(password: str, *, username: str | None = None) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")
    lowered = password.lower()
    if lowered in _DENYLIST:
        raise PasswordPolicyError("This password is too common")
    if username and lowered == username.lower():
        raise PasswordPolicyError("Password must not equal the username")
