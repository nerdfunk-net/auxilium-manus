from os import environ
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

from core.production_guards import validate_non_development_secrets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_PLUGINS_FILE = BACKEND_ROOT / "workflow_steps" / "registry.yaml"
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"

load_dotenv(DEFAULT_ENV_FILE)


class Settings:
    app_name: str = "Auxilium Manus API"
    api_prefix: str = "/api"
    environment: str
    trusted_proxy_ips: set[str]
    docs_enabled: bool
    plugins_file: Path
    secret_key: str
    access_token_expire_minutes: int
    refresh_token_max_age_hours: int
    database_host: str
    database_port: int
    database_name: str
    database_maintenance_name: str
    database_username: str
    database_password: str
    database_url: str
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
    run_retention_days: int
    run_retention_batch_size: int
    apply_safe_migrations: bool
    apply_risky_migrations: bool
    install_certificate_files: bool
    credential_encryption_key: str
    data_directory: Path
    log_directory: Path
    log_max_bytes: int
    log_backup_count: int
    allow_loopback_source_urls: bool
    netmiko_session_pooling: bool
    netmiko_pool_workers: int
    netmiko_keepalive_seconds: int
    oidc_redirect_uri_allowlist: list[str]
    allow_netmiko_arbitrary_hosts: bool

    def __init__(self) -> None:
        self.environment = environ.get("ENV", "development")
        self.trusted_proxy_ips = set(self._get_csv("TRUSTED_PROXY_IPS", ""))
        self.docs_enabled = self._get_bool("DOCS_ENABLED", self.environment == "development")
        self.plugins_file = Path(environ.get("PLUGINS_FILE", DEFAULT_PLUGINS_FILE)).resolve()
        self.secret_key = self._get_secret_key()
        self.access_token_expire_minutes = self._get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        self.refresh_token_max_age_hours = self._get_int("REFRESH_TOKEN_MAX_AGE_HOURS", 24)
        self._validate_refresh_token_max_age()
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
        self.run_retention_enabled = self._get_bool("RUN_RETENTION_ENABLED", False)
        self.run_retention_days = self._get_int("RUN_RETENTION_DAYS", 90)
        self.run_retention_batch_size = self._get_int("RUN_RETENTION_BATCH_SIZE", 500)
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
        self.log_backup_count = self._get_int("LOG_BACKUP_COUNT", 5)
        self.allow_loopback_source_urls = self._get_bool("ALLOW_LOOPBACK_SOURCE_URLS", False)
        self.netmiko_session_pooling = self._get_bool("NETMIKO_SESSION_POOLING", True)
        self.netmiko_pool_workers = self._get_int("NETMIKO_POOL_WORKERS", 10)
        self.netmiko_keepalive_seconds = self._get_int("NETMIKO_KEEPALIVE_SECONDS", 30)
        self.oidc_redirect_uri_allowlist = self._get_csv("OIDC_REDIRECT_URI_ALLOWLIST", "")
        self.allow_netmiko_arbitrary_hosts = self._get_bool(
            "ALLOW_NETMIKO_ARBITRARY_HOSTS", self.environment == "development"
        )
        validate_non_development_secrets(
            environment=self.environment,
            secret_key=self.secret_key,
            initial_password=self.initial_password,
            credential_encryption_key=self.credential_encryption_key,
            database_password=self.database_password,
        )

    def _validate_run_retention(self) -> None:
        if self.run_retention_days < 1:
            raise RuntimeError("RUN_RETENTION_DAYS must be at least 1")
        if self.run_retention_batch_size < 1:
            raise RuntimeError("RUN_RETENTION_BATCH_SIZE must be at least 1")

    def _validate_refresh_token_max_age(self) -> None:
        if self.refresh_token_max_age_hours < 1:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must be at least 1")

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
