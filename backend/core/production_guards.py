"""Pure startup guards that refuse known-unsafe defaults outside development."""

from __future__ import annotations

from core.password_policy import PASSWORD_MIN_LENGTH

DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"
WEAK_DATABASE_PASSWORDS = frozenset({"", "postgres", "password"})
MIN_SECRET_KEY_LENGTH = 32
MIN_CREDENTIAL_KEY_LENGTH = 32
MIN_INFRA_PASSWORD_LENGTH = 12
DEFAULT_CREDENTIAL_ENCRYPTION_KEYS = frozenset({DEFAULT_SECRET_KEY})
# Known placeholders for the application's Postgres / Redis passwords (S6-05).
WEAK_INFRA_PASSWORDS = frozenset(
    {"", "postgres", "password", "changeme", "admin", "redis", "secret"}
)


def _refuse_weak(name: str, value: str, *, min_length: int) -> None:
    if value.strip().lower() in WEAK_INFRA_PASSWORDS or len(value) < min_length:
        raise RuntimeError(
            f"{name} must be at least {min_length} characters and not a known default "
            "outside development"
        )


AI_PROVIDER_TOKENS = frozenset({"anthropic", "gemini", "openai_compat"})
AI_DATA_TOKENS = frozenset(
    {"inventory", "addresses", "custom_fields", "config_context", "content", "report"}
)


def validate_ai_operator_policy(*, providers: frozenset[str], data: frozenset[str]) -> None:
    """Refuse to start on an unknown ``AI_ALLOWED_PROVIDERS`` / ``AI_ALLOWED_DATA`` token.

    A typo must not silently widen or narrow what may be sent to a third-party model."""
    unknown_providers = sorted(providers - AI_PROVIDER_TOKENS)
    if unknown_providers:
        raise RuntimeError(
            f"AI_ALLOWED_PROVIDERS has unknown value(s) {unknown_providers}; "
            f"allowed: {sorted(AI_PROVIDER_TOKENS)}"
        )
    unknown_data = sorted(data - AI_DATA_TOKENS)
    if unknown_data:
        raise RuntimeError(
            f"AI_ALLOWED_DATA has unknown value(s) {unknown_data}; "
            f"allowed: {sorted(AI_DATA_TOKENS)}"
        )


def ai_policy_warnings(
    *, enabled: bool, providers: frozenset[str], data: frozenset[str]
) -> list[str]:
    """Provider / data limits are policy, not secrets: a limit set while the assistant is off
    is logged, never refused."""
    if enabled or not (providers or data):
        return []
    return [
        "AI_ALLOWED_PROVIDERS / AI_ALLOWED_DATA are set but AI_ASSISTANT_ENABLED is false; "
        "the assistant stays off"
    ]


def collect_startup_warnings(
    *,
    environment: str,
    docs_enabled: bool,
    allow_loopback_source_urls: bool,
    max_request_body_bytes: int,
) -> list[str]:
    """Deliberate policy relaxations: logged once per setting, never refused."""
    if environment == "development":
        return []
    out: list[str] = []
    if docs_enabled:
        out.append("DOCS_ENABLED=true exposes /docs, /redoc and /openapi.json")
    if allow_loopback_source_urls:
        out.append("ALLOW_LOOPBACK_SOURCE_URLS=true relaxes the SSRF policy for loopback targets")
    if max_request_body_bytes == 0:
        out.append("MAX_REQUEST_BODY_BYTES=0 disables the request body limit")
    return out


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
    trusted_proxy_ips_configured: bool = True,
    vault_enabled: bool = False,
    vault_addr: str = "",
    vault_verify_ssl: bool = True,
    vault_auth_method: str = "approle",
    vault_role_id: str = "",
    vault_secret_id: str = "",
    vault_secret_id_file: str = "",
    vault_client_cert: str = "",
    vault_client_key: str = "",
    vault_manage_role_id: str = "",
    vault_manage_secret_id: str = "",
    vault_manage_secret_id_file: str = "",
    process_role: str = "web",
) -> None:
    """Refuse weak or default configuration outside development.

    ``process_role`` is ``web`` (API + frontend) or ``worker`` (Hatchet workers). Only the web
    process seeds the admin account and writes credentials to OpenBao, so a worker is not given
    ``INITIAL_PASSWORD`` or the management role and is not required to have them.
    """
    if environment == "development":
        return
    web = process_role == "web"
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters outside development"
        )
    if web and initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
    if web and len(initial_password) < PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            f"INITIAL_PASSWORD must be at least {PASSWORD_MIN_LENGTH} characters "
            "outside development"
        )
    if not credential_encryption_key.strip():
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be configured outside development")
    if credential_encryption_key == secret_key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must differ from SECRET_KEY")
    if (
        len(credential_encryption_key) < MIN_CREDENTIAL_KEY_LENGTH
        or credential_encryption_key in DEFAULT_CREDENTIAL_ENCRYPTION_KEYS
    ):
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY must be a random value of at least "
            f"{MIN_CREDENTIAL_KEY_LENGTH} characters (openssl rand -hex 32)"
        )
    if database_password in WEAK_DATABASE_PASSWORDS:
        raise RuntimeError("DATABASE_PASSWORD must be configured outside development")
    _refuse_weak("DATABASE_PASSWORD", database_password, min_length=MIN_INFRA_PASSWORD_LENGTH)
    if enable_dev_tools:
        raise RuntimeError("ENABLE_DEV_TOOLS must not be set outside development")
    if not redis_password.strip():
        raise RuntimeError("MANUS_REDIS_PASSWORD must be configured outside development")
    _refuse_weak("MANUS_REDIS_PASSWORD", redis_password, min_length=MIN_INFRA_PASSWORD_LENGTH)
    if allow_netmiko_arbitrary_hosts:
        raise RuntimeError("ALLOW_NETMIKO_ARBITRARY_HOSTS must not be enabled outside development")
    if not trusted_proxy_ips_configured:
        raise RuntimeError(
            "TRUSTED_PROXY_IPS must be set outside development: the backend is only reached "
            "through the Next.js proxy, so without it every login shares one rate-limit bucket. "
            "Use 127.0.0.1 for the all-in-one image, or the proxy's IP/CIDR for a split deployment"
        )
    if vault_enabled:
        if not vault_addr.lower().startswith("https://"):
            raise RuntimeError("VAULT_ADDR must use https outside development")
        if not vault_verify_ssl:
            raise RuntimeError(
                "VAULT_VERIFY_SSL must not be disabled outside development "
                "(point VAULT_CACERT at the OpenBao CA bundle instead)"
            )
        if vault_auth_method == "token":
            raise RuntimeError("VAULT_AUTH_METHOD=token is only allowed in development")
        if vault_auth_method == "approle":
            if not vault_role_id.strip():
                raise RuntimeError("VAULT_ROLE_ID must be set for AppRole auth outside development")
            if not (vault_secret_id.strip() or vault_secret_id_file.strip()):
                raise RuntimeError(
                    "VAULT_SECRET_ID or VAULT_SECRET_ID_FILE must be set outside development"
                )
            if web and not vault_manage_role_id.strip():
                raise RuntimeError(
                    "VAULT_MANAGE_ROLE_ID must be set (management role is required "
                    "when VAULT_ENABLED)"
                )
            if web and not (vault_manage_secret_id.strip() or vault_manage_secret_id_file.strip()):
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
