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
    enable_dev_tools: bool = False,
    redis_password: str = "",
    allow_netmiko_arbitrary_hosts: bool = False,
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
    if enable_dev_tools:
        raise RuntimeError("ENABLE_DEV_TOOLS must not be set outside development")
    if not redis_password.strip():
        raise RuntimeError("MANUS_REDIS_PASSWORD must be configured outside development")
    if allow_netmiko_arbitrary_hosts:
        raise RuntimeError("ALLOW_NETMIKO_ARBITRARY_HOSTS must not be enabled outside development")
