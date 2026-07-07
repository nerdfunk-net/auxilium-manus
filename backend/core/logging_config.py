"""Shared logging configuration for the API server and the Hatchet worker."""

from __future__ import annotations

import logging
import logging.config

from core.config import settings

_NOISY_LOGGERS = ["watchfiles", "watchfiles.main"]


def _get_log_level() -> int:
    level = logging.getLevelName(settings.log_level.upper())

    if not isinstance(level, int):
        level = logging.INFO
        print(f"Warning: invalid LOG_LEVEL '{settings.log_level}', defaulting to INFO")  # noqa: T201

    return level


def configure_logging(process_name: str) -> dict[str, object]:
    """Configure the root logger with a stdout handler and a rotating file handler.

    process_name distinguishes the log file per process (e.g. "app", "worker")
    so both can share settings.log_directory without clobbering each other.
    """
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    level = _get_log_level()

    log_config: dict[str, object] = {
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
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": str(settings.log_directory / f"{process_name}.log"),
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
            },
        },
        "root": {
            "level": level,
            "handlers": ["default", "file"],
        },
        "loggers": {
            "uvicorn": {
                "level": level,
                "handlers": ["default", "file"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
                "handlers": ["default", "file"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": level,
                "handlers": ["default", "file"],
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(log_config)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return log_config
