import logging
from ipaddress import IPv4Network, IPv6Network, ip_network
from os import environ
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import dotenv_values, load_dotenv

from core import crypto_policy
from core.production_guards import (
    ai_policy_warnings,
    collect_startup_warnings,
    validate_ai_operator_policy,
    validate_non_development_secrets,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
# Source directory for operator-supplied CA certificates (bind-mounted in Docker) and
# the system trust anchor they are copied into. Shared by core.cert_installer (startup
# install, gated by INSTALL_CERTIFICATE_FILES) and services.certificates (admin API).
CONFIG_CERTS_DIR = PROJECT_ROOT / "config" / "certs"
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
DEFAULT_PLUGINS_FILE = BACKEND_ROOT / "workflow_steps" / "registry.yaml"
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"
DEFAULT_ALLOWED_FILE_EXTENSIONS = ".cfg,.conf,.txt,.yaml,.yml,.json,.xml,.ini,.md"


def _load_dotenv_for_development() -> None:
    """Load ``backend/.env`` only for a development run.

    A production image never reads that file (S6-02): even if one was copied into the image by
    mistake, its dev-only switches (``ENABLE_DEV_TOOLS``, ``ALLOW_LOOPBACK_SOURCE_URLS``, ...)
    cannot take effect. ``ENV`` is peeked at first: the process environment wins, then the file
    itself, and an unset value counts as production.
    """
    # MANUS_ENV_FILE points elsewhere (tests use /dev/null so a developer's own file is never read).
    env_file = Path(environ.get("MANUS_ENV_FILE") or DEFAULT_ENV_FILE)
    effective = environ.get("ENV")
    if effective is None:
        effective = str(dotenv_values(env_file).get("ENV") or "production")
    if effective == "development":
        load_dotenv(env_file)


_load_dotenv_for_development()


TrustedProxyNetworks = frozenset[IPv4Network | IPv6Network]


def validate_trusted_proxy_ips(values: set[str]) -> TrustedProxyNetworks:
    """Parse TRUSTED_PROXY_IPS entries (bare IPs or CIDRs) into networks.

    A bare IP becomes a /32 (/128) network. Rejects unparsable entries, the
    unspecified address (0.0.0.0 / ::), and catch-all networks (/0).
    """
    cleaned: set[IPv4Network | IPv6Network] = set()
    for raw in values:
        try:
            network = ip_network(raw, strict=False)
        except ValueError as exc:
            raise RuntimeError(f"TRUSTED_PROXY_IPS contains an invalid IP or CIDR: {raw}") from exc
        if network.prefixlen == 0:
            raise RuntimeError(f"TRUSTED_PROXY_IPS must not include a catch-all network: {raw}")
        if network.network_address.is_unspecified:
            raise RuntimeError(f"TRUSTED_PROXY_IPS must not include unspecified address {raw}")
        cleaned.add(network)
    return frozenset(cleaned)


class Settings:
    app_name: str = "Auxilium Manus API"
    api_prefix: str = "/api"
    environment: str
    trusted_proxy_networks: TrustedProxyNetworks
    docs_enabled: bool
    plugins_file: Path
    secret_key: str
    access_token_expire_minutes: int
    refresh_token_max_age_hours: int
    session_max_age_hours: int
    kdf_iterations: int
    database_host: str
    database_port: int
    database_name: str
    database_maintenance_name: str
    database_username: str
    database_password: str
    database_url: str
    database_pool_size: int
    database_max_overflow: int
    database_pool_timeout: int
    maintenance_database_url: str
    initial_username: str
    initial_password: str
    log_level: str
    log_format: str
    redis_host: str
    redis_port: int
    redis_password: str
    redis_url: str
    redis_key_prefix: str
    run_retention_enabled: bool
    rate_limit_fail_closed: bool
    git_repo_lock_required: bool
    run_retention_days: int
    run_retention_batch_size: int
    run_retention_cron_schedule: str
    run_reaper_cron_schedule: str
    run_reaper_grace_minutes: int
    ai_conversation_retention_days: int
    process_role: str
    ai_assistant_enabled: bool
    ai_allowed_providers: frozenset[str]
    ai_allowed_data: frozenset[str]
    apply_safe_migrations: bool
    apply_risky_migrations: bool
    install_certificate_files: bool
    credential_encryption_key: str
    data_directory: Path
    log_directory: Path
    log_max_bytes: int
    max_request_body_bytes: int
    log_backup_count: int
    allow_loopback_source_urls: bool
    netmiko_session_pooling: bool
    netmiko_pool_workers: int
    netmiko_keepalive_seconds: int
    oidc_redirect_uri_allowlist: list[str]
    allow_netmiko_arbitrary_hosts: bool
    allowed_file_extensions: list[str]
    vault_enabled: bool
    vault_addr: str
    vault_kv_mount: str
    vault_namespace: str
    vault_auth_method: str
    vault_role_id: str
    vault_secret_id: str
    vault_secret_id_file: str
    vault_token: str
    vault_client_cert: str
    vault_client_key: str
    vault_ca_cert: str
    vault_verify_ssl: bool
    vault_token_period_seconds: int
    vault_renew_buffer_seconds: int
    vault_timeout_seconds: int
    vault_cache_ttl_seconds: int
    vault_manage_role_id: str
    vault_manage_secret_id: str
    vault_manage_secret_id_file: str
    vault_manage_token: str

    def __init__(self) -> None:
        self.environment = environ.get("ENV", "production")  # development is an explicit choice
        self.trusted_proxy_networks = validate_trusted_proxy_ips(
            set(self._get_csv("TRUSTED_PROXY_IPS", ""))
        )
        self.docs_enabled = self._get_bool("DOCS_ENABLED", self.environment == "development")
        self.plugins_file = Path(environ.get("PLUGINS_FILE", DEFAULT_PLUGINS_FILE)).resolve()
        self.secret_key = self._get_secret_key()
        self.access_token_expire_minutes = self._get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        # Absolute session lifetime measured from the original login (claim
        # `sid_iat`), carried unchanged through every refresh. Independent of the
        # sliding access-token TTL and the refresh grace window.
        self.session_max_age_hours = self._get_int("SESSION_MAX_AGE_HOURS", 12)
        self._validate_session_max_age()
        self._validate_access_token_expiry()
        # How stale an expired access token may be when exchanged. Anything above
        # the absolute session cap is unreachable, so it is refused (T4).
        self.refresh_token_max_age_hours = self._get_int(
            "REFRESH_TOKEN_MAX_AGE_HOURS", self.session_max_age_hours
        )
        self._validate_refresh_token_max_age()
        # PBKDF2 iteration count for deriving the credential-encryption Fernet key
        # (core/crypto.py). Read here, not via raw os.getenv, so it is validated
        # once and visible in Settings.
        self.kdf_iterations = self._get_int("KDF_ITERATIONS", crypto_policy.KDF_ITERATIONS_FLOOR)
        self._validate_kdf_iterations()
        self.database_host = environ.get("DATABASE_HOST", "localhost")
        self.database_port = self._get_int("DATABASE_PORT", 5432)
        self.database_name = environ.get("DATABASE_NAME", "manus")
        self.database_maintenance_name = environ.get("DATABASE_MAINTENANCE_NAME", "postgres")
        self.database_username = environ.get("DATABASE_USERNAME", "postgres")
        self.database_password = environ.get("DATABASE_PASSWORD", "postgres")
        self.database_url = environ.get("DATABASE_URL", self._build_database_url())
        self.maintenance_database_url = environ.get(
            "MAINTENANCE_DATABASE_URL",
            self._build_database_url(database_name=self.database_maintenance_name),
        )
        self.initial_username = environ.get("INITIAL_USERNAME", "admin")
        self.initial_password = environ.get("INITIAL_PASSWORD", DEFAULT_INITIAL_PASSWORD)
        self.log_level = environ.get("LOG_LEVEL", "INFO")
        self.log_format = environ.get(
            "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.redis_host = environ.get("MANUS_REDIS_HOST", "localhost")
        self.redis_port = self._get_int("MANUS_REDIS_PORT", 6379)
        self.redis_password = environ.get("MANUS_REDIS_PASSWORD", "")
        self.redis_key_prefix = environ.get("MANUS_REDIS_KEY_PREFIX", "manus-cache")
        self.redis_url = environ.get("MANUS_REDIS_URL", self._build_redis_url())
        self.run_retention_enabled = self._get_bool("RUN_RETENTION_ENABLED", True)
        # Login, refresh, OIDC-login and webhook limiters count in Redis. When Redis is unreachable
        # they fall back to an in-process window (exact with one web process, per-replica with
        # several). True refuses the request instead, which locks everybody out of login until Redis
        # is back (O2-02); only worth it behind several replicas.
        self.rate_limit_fail_closed = self._get_bool("RATE_LIMIT_FAIL_CLOSED", False)
        # A git step takes a per-repository lock in Redis. Where Redis is part of the deployment
        # (every non-development run: the compose file requires it) a step that cannot get the lock
        # fails with a retryable error instead of mutating the shared working tree unprotected
        # (O2-05). Development without Redis keeps working unlocked.
        self.git_repo_lock_required = self._get_bool(
            "GIT_REPO_LOCK_REQUIRED", self.environment != "development"
        )
        self.run_retention_days = self._get_int("RUN_RETENTION_DAYS", 90)
        self.run_retention_batch_size = self._get_int("RUN_RETENTION_BATCH_SIZE", 500)
        self.run_retention_cron_schedule = environ.get("RUN_RETENTION_CRON_SCHEDULE", "0 3 * * *")
        # Reaper for runs the orchestration could not finalise (worker lost, timeout).
        self.run_reaper_cron_schedule = environ.get("RUN_REAPER_CRON_SCHEDULE", "*/10 * * * *")
        self.run_reaper_grace_minutes = self._get_int("RUN_REAPER_GRACE_MINUTES", 15)
        # Cap of the step output persisted with a step result (the live context is not capped):
        # one value above the first limit, or a payload above the second, is replaced by a marker.
        self.step_output_value_max_bytes = self._get_int("STEP_OUTPUT_VALUE_MAX_BYTES", 65_536)
        self.step_output_max_bytes = self._get_int("STEP_OUTPUT_MAX_BYTES", 8_388_608)
        # Saved AI assistant conversations; 0 keeps them until the user deletes them.
        self.ai_conversation_retention_days = self._get_int("AI_CONVERSATION_RETENTION_DAYS", 90)
        # Operator switches for the AI assistant (S5-09): off, no provider and no data by default.
        # A user's own settings can only narrow what is set here.
        # ``web`` (API + frontend, the default) or ``worker`` (Hatchet workers): a worker is not
        # given INITIAL_PASSWORD or the OpenBao management role (see production_guards).
        self.process_role = environ.get("MANUS_PROCESS_ROLE", "web").strip().lower()
        if self.process_role not in ("web", "worker"):
            raise RuntimeError("MANUS_PROCESS_ROLE must be 'web' or 'worker'")
        # Connection pool: a worker holds a session per live step/event, so it defaults larger.
        # Sizing: concurrent Hatchet slots x steps that hold a session at once (see
        # doc/claude/development.md).
        is_worker = self.process_role == "worker"
        self.database_pool_size = self._get_int("DATABASE_POOL_SIZE", 20 if is_worker else 10)
        self.database_max_overflow = self._get_int("DATABASE_MAX_OVERFLOW", 20 if is_worker else 10)
        self.database_pool_timeout = self._get_int("DATABASE_POOL_TIMEOUT", 30)
        if self.database_pool_size < 1:
            raise RuntimeError("DATABASE_POOL_SIZE must be at least 1")
        if self.database_max_overflow < 0:
            raise RuntimeError("DATABASE_MAX_OVERFLOW must be 0 or greater")
        if self.database_pool_timeout < 1:
            raise RuntimeError("DATABASE_POOL_TIMEOUT must be at least 1")
        self.ai_assistant_enabled = self._get_bool("AI_ASSISTANT_ENABLED", False)
        self.ai_allowed_providers = frozenset(self._get_csv("AI_ALLOWED_PROVIDERS", ""))
        self.ai_allowed_data = frozenset(self._get_csv("AI_ALLOWED_DATA", ""))
        validate_ai_operator_policy(providers=self.ai_allowed_providers, data=self.ai_allowed_data)
        for message in ai_policy_warnings(
            enabled=self.ai_assistant_enabled,
            providers=self.ai_allowed_providers,
            data=self.ai_allowed_data,
        ):
            logger.warning("Startup configuration: %s", message)
        # Report data rows (report_data_records); 0 keeps them. The newest collection of each
        # device and dataset is always kept.
        self.report_data_retention_days = self._get_int("REPORT_DATA_RETENTION_DAYS", 365)
        self._validate_run_retention()
        self.apply_safe_migrations = self._get_bool("APPLY_SAFE_DATABASE_MIGRATION", False)
        self.apply_risky_migrations = self._get_bool("APPLY_RISKY_DATABASE_MIGRATION", False)
        self.install_certificate_files = self._get_bool("INSTALL_CERTIFICATE_FILES", False)
        self.credential_encryption_key = environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
        self.data_directory = Path(environ.get("DATA_DIRECTORY", PROJECT_ROOT / "data")).resolve()
        self.log_directory = Path(
            environ.get("LOG_DIRECTORY", self.data_directory / "logs")
        ).resolve()
        self.log_max_bytes = self._get_int("LOG_MAX_BYTES", 10_485_760)
        # Reject requests that announce a body larger than this (0 disables). A reverse proxy
        # should enforce its own limit too; this guards the direct-access / chunked-less case.
        self.max_request_body_bytes = self._get_int("MAX_REQUEST_BODY_BYTES", 25 * 1024 * 1024)
        if self.max_request_body_bytes < 0:
            raise RuntimeError("MAX_REQUEST_BODY_BYTES must be 0 (disabled) or positive")
        self.log_backup_count = self._get_int("LOG_BACKUP_COUNT", 5)
        self.allow_loopback_source_urls = self._get_bool("ALLOW_LOOPBACK_SOURCE_URLS", False)
        self.netmiko_session_pooling = self._get_bool("NETMIKO_SESSION_POOLING", True)
        self.netmiko_pool_workers = self._get_int("NETMIKO_POOL_WORKERS", 10)
        self.netmiko_keepalive_seconds = self._get_int("NETMIKO_KEEPALIVE_SECONDS", 30)
        self.oidc_redirect_uri_allowlist = self._get_csv("OIDC_REDIRECT_URI_ALLOWLIST", "")
        self.allow_netmiko_arbitrary_hosts = self._get_bool(
            "ALLOW_NETMIKO_ARBITRARY_HOSTS", self.environment == "development"
        )
        self.allowed_file_extensions = self._get_csv(
            "ALLOWED_FILE_EXTENSIONS", DEFAULT_ALLOWED_FILE_EXTENSIONS
        )
        # OpenBao (Vault) — optional external secret storage. All env-based, like
        # DATABASE_* / SECRET_KEY; never a Settings-KV row. See doc/VAULT_INTEGRATION.md.
        self.vault_enabled = self._get_bool("VAULT_ENABLED", False)
        self.vault_addr = environ.get("VAULT_ADDR", "")
        self.vault_kv_mount = environ.get("VAULT_KV_MOUNT", "manus")
        self.vault_namespace = environ.get("VAULT_NAMESPACE", "")
        self.vault_auth_method = environ.get("VAULT_AUTH_METHOD", "approle")
        self.vault_role_id = environ.get("VAULT_ROLE_ID", "")
        self.vault_secret_id = environ.get("VAULT_SECRET_ID", "")
        self.vault_secret_id_file = environ.get("VAULT_SECRET_ID_FILE", "")
        self.vault_token = environ.get("VAULT_TOKEN", "")
        self.vault_client_cert = environ.get("VAULT_CLIENT_CERT", "")
        self.vault_client_key = environ.get("VAULT_CLIENT_KEY", "")
        self.vault_ca_cert = environ.get("VAULT_CACERT", "")
        self.vault_verify_ssl = self._get_bool("VAULT_VERIFY_SSL", True)
        self.vault_token_period_seconds = self._get_int("VAULT_TOKEN_PERIOD_SECONDS", 3600)
        self.vault_renew_buffer_seconds = self._get_int("VAULT_RENEW_BUFFER_SECONDS", 600)
        self.vault_timeout_seconds = self._get_int("VAULT_TIMEOUT_SECONDS", 5)
        self.vault_cache_ttl_seconds = self._get_int("VAULT_CACHE_TTL_SECONDS", 45)
        self.vault_manage_role_id = environ.get("VAULT_MANAGE_ROLE_ID", "")
        self.vault_manage_secret_id = environ.get("VAULT_MANAGE_SECRET_ID", "")
        self.vault_manage_secret_id_file = environ.get("VAULT_MANAGE_SECRET_ID_FILE", "")
        self.vault_manage_token = environ.get("VAULT_MANAGE_TOKEN", "")
        self._validate_vault()
        from core.dev_tools import dev_tools_enabled

        validate_non_development_secrets(
            environment=self.environment,
            secret_key=self.secret_key,
            initial_password=self.initial_password,
            credential_encryption_key=self.credential_encryption_key,
            database_password=self.database_password,
            enable_dev_tools=dev_tools_enabled(),
            redis_password=self.redis_password,
            allow_netmiko_arbitrary_hosts=self.allow_netmiko_arbitrary_hosts,
            trusted_proxy_ips_configured=bool(self.trusted_proxy_networks),
            vault_enabled=self.vault_enabled,
            vault_addr=self.vault_addr,
            vault_verify_ssl=self.vault_verify_ssl,
            vault_auth_method=self.vault_auth_method,
            vault_role_id=self.vault_role_id,
            vault_secret_id=self.vault_secret_id,
            vault_secret_id_file=self.vault_secret_id_file,
            vault_client_cert=self.vault_client_cert,
            vault_client_key=self.vault_client_key,
            vault_manage_role_id=self.vault_manage_role_id,
            vault_manage_secret_id=self.vault_manage_secret_id,
            vault_manage_secret_id_file=self.vault_manage_secret_id_file,
            process_role=self.process_role,
        )
        for message in collect_startup_warnings(
            environment=self.environment,
            docs_enabled=self.docs_enabled,
            allow_loopback_source_urls=self.allow_loopback_source_urls,
            max_request_body_bytes=self.max_request_body_bytes,
        ):
            logger.warning("Startup configuration: %s", message)

    def _validate_run_retention(self) -> None:
        if self.run_retention_days < 1:
            raise RuntimeError("RUN_RETENTION_DAYS must be at least 1")
        if self.run_retention_batch_size < 1:
            raise RuntimeError("RUN_RETENTION_BATCH_SIZE must be at least 1")
        if not self.run_retention_cron_schedule.strip():
            raise RuntimeError("RUN_RETENTION_CRON_SCHEDULE must not be empty")
        if not self.run_reaper_cron_schedule.strip():
            raise RuntimeError("RUN_REAPER_CRON_SCHEDULE must not be empty")
        if self.run_reaper_grace_minutes < 1:
            raise RuntimeError("RUN_REAPER_GRACE_MINUTES must be at least 1")
        if self.step_output_value_max_bytes < 1024:
            raise RuntimeError("STEP_OUTPUT_VALUE_MAX_BYTES must be at least 1024")
        if self.step_output_max_bytes < self.step_output_value_max_bytes:
            raise RuntimeError(
                "STEP_OUTPUT_MAX_BYTES must not be below STEP_OUTPUT_VALUE_MAX_BYTES"
            )
        if self.ai_conversation_retention_days < 0:
            raise RuntimeError("AI_CONVERSATION_RETENTION_DAYS must be 0 or greater")
        if self.report_data_retention_days < 0:
            raise RuntimeError("REPORT_DATA_RETENTION_DAYS must be 0 or greater")

    def _validate_vault(self) -> None:
        """Structural, environment-agnostic checks for the OpenBao settings.

        Secret-strength / TLS / production-only checks live in
        core.production_guards.validate_non_development_secrets.
        """
        if not self.vault_enabled:
            return
        if not self.vault_addr.strip():
            raise RuntimeError("VAULT_ADDR must be set when VAULT_ENABLED=true")
        from urllib.parse import urlparse

        parsed = urlparse(self.vault_addr)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise RuntimeError("VAULT_ADDR must be a valid http(s) URL")
        if self.vault_auth_method not in ("approle", "cert", "token"):
            raise RuntimeError("VAULT_AUTH_METHOD must be one of: approle, cert, token")
        if self.vault_token_period_seconds < 60:
            raise RuntimeError("VAULT_TOKEN_PERIOD_SECONDS must be at least 60")
        if self.vault_renew_buffer_seconds >= self.vault_token_period_seconds:
            raise RuntimeError(
                "VAULT_RENEW_BUFFER_SECONDS must be smaller than VAULT_TOKEN_PERIOD_SECONDS"
            )
        if not 30 <= self.vault_cache_ttl_seconds <= 300:
            raise RuntimeError("VAULT_CACHE_TTL_SECONDS must be between 30 and 300")

    def _validate_refresh_token_max_age(self) -> None:
        if self.refresh_token_max_age_hours < 1:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must be at least 1")
        if self.refresh_token_max_age_hours > self.session_max_age_hours:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must not exceed SESSION_MAX_AGE_HOURS")

    def _validate_access_token_expiry(self) -> None:
        if not 1 <= self.access_token_expire_minutes <= 1440:
            raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 1440")

    def _validate_session_max_age(self) -> None:
        if self.session_max_age_hours < 1:
            raise RuntimeError("SESSION_MAX_AGE_HOURS must be at least 1")

    def _validate_kdf_iterations(self) -> None:
        floor, ceiling = crypto_policy.KDF_ITERATIONS_FLOOR, crypto_policy.KDF_ITERATIONS_CEILING
        if not floor <= self.kdf_iterations <= ceiling:
            raise RuntimeError(f"KDF_ITERATIONS must be between {floor} and {ceiling}")

    def _build_redis_url(self) -> str:
        if self.redis_password:
            return (
                f"redis://:{quote_plus(self.redis_password)}@{self.redis_host}:{self.redis_port}/0"
            )
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    def _build_database_url(self, database_name: str | None = None) -> str:
        username = quote_plus(self.database_username)
        password = quote_plus(self.database_password)
        database = quote_plus(database_name or self.database_name)

        return (
            f"postgresql+psycopg://{username}:{password}"
            f"@{self.database_host}:{self.database_port}/{database}"
        )

    @staticmethod
    def _get_secret_key() -> str:
        return environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

    @staticmethod
    def _get_int(name: str, default: int) -> int:
        raw_value = environ.get(name)

        if raw_value is None:
            return default

        try:
            return int(raw_value)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc

    @staticmethod
    def _get_bool(name: str, default: bool) -> bool:
        raw_value = environ.get(name)

        if raw_value is None:
            return default

        return raw_value.lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_csv(name: str, default: str) -> list[str]:
        raw_value = environ.get(name, default)

        return [value.strip() for value in raw_value.split(",") if value.strip()]


settings = Settings()
