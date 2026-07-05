import logging
import logging.config
import os
import sys
from pathlib import Path

# Ensure the backend directory is on sys.path so workflow_steps packages are importable.
sys.path.insert(0, str(Path(__file__).parent))

from core.config import settings  # noqa: E402 — loads .env via load_dotenv()

_NOISY_LOGGERS = ["watchfiles", "watchfiles.main"]


def _get_log_level() -> int:
    level = logging.getLevelName(settings.log_level.upper())

    if not isinstance(level, int):
        level = logging.INFO
        print(f"Warning: invalid LOG_LEVEL '{settings.log_level}', defaulting to INFO")  # noqa: T201

    return level


def _build_log_config(level: int) -> dict[str, object]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": settings.log_format,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": level,
            "handlers": ["default"],
        },
        "loggers": {
            "uvicorn": {
                "level": level,
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": level,
                "handlers": ["default"],
                "propagate": False,
            },
        },
    }


def _configure_logging() -> dict[str, object]:
    level = _get_log_level()
    log_config = _build_log_config(level)
    logging.config.dictConfig(log_config)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return log_config


if __name__ == "__main__":
    import uvicorn

    log_config = _configure_logging()

    logger = logging.getLogger(__name__)
    logger.debug("Log level: %s", settings.log_level)

    is_development = settings.environment == "development"

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("BACKEND_PORT", "8001"))

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=is_development,
        log_config=log_config,
        log_level=settings.log_level.lower(),
    )
