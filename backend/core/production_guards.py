"""Pure startup guards that refuse known-unsafe defaults outside development."""

from __future__ import annotations

DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"
WEAK_DATABASE_PASSWORDS = frozenset({"", "postgres", "password"})


def validate_non_development_secrets(
    *,
    environment: str,
    secret_key: str,
    initial_password: str,
    credential_encryption_key: str,
    database_password: str,
) -> None:
    if environment == "development":
        return
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
    if not credential_encryption_key.strip():
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be configured outside development")
    if credential_encryption_key == secret_key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must differ from SECRET_KEY")
    if database_password in WEAK_DATABASE_PASSWORDS:
        raise RuntimeError("DATABASE_PASSWORD must be configured outside development")
