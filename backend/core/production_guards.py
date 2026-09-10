"""Pure startup guards that refuse known-unsafe defaults outside development."""

from __future__ import annotations

from services.auth.password_policy import PASSWORD_MIN_LENGTH

DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"
WEAK_DATABASE_PASSWORDS = frozenset({"", "postgres", "password"})
MIN_SECRET_KEY_LENGTH = 32


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
    vault_enabled: bool = False,
    vault_addr: str = "",
    vault_auth_method: str = "approle",
    vault_role_id: str = "",
    vault_secret_id: str = "",
    vault_secret_id_file: str = "",
    vault_client_cert: str = "",
    vault_client_key: str = "",
    vault_manage_role_id: str = "",
    vault_manage_secret_id: str = "",
    vault_manage_secret_id_file: str = "",
) -> None:
    if environment == "development":
        return
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters outside development"
        )
    if initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
    if len(initial_password) < PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            f"INITIAL_PASSWORD must be at least {PASSWORD_MIN_LENGTH} characters "
            "outside development"
        )
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
    if vault_enabled:
        if not vault_addr.lower().startswith("https://"):
            raise RuntimeError("VAULT_ADDR must use https outside development")
        if vault_auth_method == "token":
            raise RuntimeError("VAULT_AUTH_METHOD=token is only allowed in development")
        if vault_auth_method == "approle":
            if not vault_role_id.strip():
                raise RuntimeError(
                    "VAULT_ROLE_ID must be set for AppRole auth outside development"
                )
            if not (vault_secret_id.strip() or vault_secret_id_file.strip()):
                raise RuntimeError(
                    "VAULT_SECRET_ID or VAULT_SECRET_ID_FILE must be set outside development"
                )
            if not vault_manage_role_id.strip():
                raise RuntimeError(
                    "VAULT_MANAGE_ROLE_ID must be set (management role is required "
                    "when VAULT_ENABLED)"
                )
            if not (vault_manage_secret_id.strip() or vault_manage_secret_id_file.strip()):
                raise RuntimeError(
                    "VAULT_MANAGE_SECRET_ID or VAULT_MANAGE_SECRET_ID_FILE must be set "
                    "outside development"
                )
        if vault_auth_method == "cert" and not (
            vault_client_cert.strip() and vault_client_key.strip()
        ):
            raise RuntimeError(
                "VAULT_CLIENT_CERT and VAULT_CLIENT_KEY must be set for cert auth "
                "outside development"
            )
