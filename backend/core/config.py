from os import environ
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

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
    initial_permissions: int
    log_level: str
    log_format: str
    redis_host: str
    redis_port: int
    redis_password: str
    redis_url: str
    redis_key_prefix: str

    def __init__(self) -> None:
        self.environment = environ.get("ENV", "development")
        self.trusted_proxy_ips = set(self._get_csv("TRUSTED_PROXY_IPS", ""))
        self.docs_enabled = self._get_bool("DOCS_ENABLED", self.environment == "development")
        self.plugins_file = Path(environ.get("PLUGINS_FILE", DEFAULT_PLUGINS_FILE)).resolve()
        self.secret_key = self._get_secret_key()
        self.access_token_expire_minutes = self._get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
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
        self._validate_initial_password()
        self.initial_permissions = self._get_int("INITIAL_PERMISSIONS", 15)
        self.log_level = environ.get("LOG_LEVEL", "INFO")
        self.log_format = environ.get(
            "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.redis_host = environ.get("MANUS_REDIS_HOST", "localhost")
        self.redis_port = self._get_int("MANUS_REDIS_PORT", 6379)
        self.redis_password = environ.get("MANUS_REDIS_PASSWORD", "")
        self.redis_key_prefix = environ.get("MANUS_REDIS_KEY_PREFIX", "manus-cache")
        self.redis_url = environ.get("MANUS_REDIS_URL", self._build_redis_url())

    def _build_redis_url(self) -> str:
        if self.redis_password:
            return (
                f"redis://:{quote_plus(self.redis_password)}"
                f"@{self.redis_host}:{self.redis_port}/0"
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

    def _get_secret_key(self) -> str:
        secret_key = environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

        if self.environment != "development" and secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError("SECRET_KEY must be configured outside development")

        return secret_key

    def _validate_initial_password(self) -> None:
        if self.environment != "development" and self.initial_password == DEFAULT_INITIAL_PASSWORD:
            raise RuntimeError("INITIAL_PASSWORD must be configured outside development")

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
