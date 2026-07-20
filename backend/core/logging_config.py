"""Shared logging configuration for the API server and the Hatchet worker."""

from __future__ import annotations

import logging
import logging.config
from typing import Any

from core.config import settings

# Third-party loggers that are noisy at INFO/DEBUG and drown out application
# logs (grpc DEBUG chatter from Hatchet's client, netmiko/paramiko per-command
# tracing, etc). Overridable at runtime via the Settings / Logging page.
DEFAULT_MUTED_LOGGERS: dict[str, str] = {
    "watchfiles": "WARNING",
    "watchfiles.main": "WARNING",
    "netmiko": "WARNING",
    "paramiko": "WARNING",
    "paramiko.transport": "WARNING",
    "grpc": "WARNING",
    "grpc._cython.cygrpc": "WARNING",
    "hpack": "WARNING",
}

# Logger name prefixes that make up "workflow execution" output: step
# start/finish/failure from the runner, plus every workflow_steps/*/executor.py
# module (logging.getLogger(__name__) gives them names like
# "workflow_steps.run_command.executor", which is a child of "workflow_steps").
# Configuring just these two ancestor loggers is enough to capture every
# descendant without touching each executor file.
WORKFLOW_LOGGER_NAMES = ("workflow_steps", "services.execution")


def _get_log_level(name: str) -> int:
    level = logging.getLevelName(name.upper())

    if not isinstance(level, int):
        level = logging.INFO
        print(f"Warning: invalid log level '{name}', defaulting to INFO")  # noqa: T201

    return level


def _build_log_config(
    process_name: str,
    *,
    default_level: str,
    workflow_log_enabled: bool,
    workflow_log_level: str,
    workflow_log_max_bytes: int,
    workflow_log_backup_count: int,
    muted_loggers: dict[str, str],
) -> dict[str, Any]:
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    level = _get_log_level(default_level)

    handlers: dict[str, Any] = {
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
    }

    loggers: dict[str, Any] = {
        "uvicorn": {"level": level, "handlers": ["default", "file"], "propagate": False},
        "uvicorn.error": {"level": level, "handlers": ["default", "file"], "propagate": False},
        "uvicorn.access": {"level": level, "handlers": ["default", "file"], "propagate": False},
    }

    if workflow_log_enabled:
        handlers["workflow_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": str(settings.log_directory / "workflow.log"),
            "maxBytes": workflow_log_max_bytes,
            "backupCount": workflow_log_backup_count,
        }
        workflow_level = _get_log_level(workflow_log_level)
        for name in WORKFLOW_LOGGER_NAMES:
            loggers[name] = {
                "level": workflow_level,
                "handlers": ["workflow_file"],
                # Keep propagating so app.log/worker.log still see everything —
                # workflow.log is a filtered *copy*, not the only record.
                "propagate": True,
            }

    for name, muted_level in muted_loggers.items():
        loggers[name] = {"level": _get_log_level(muted_level), "propagate": True}

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": settings.log_format,
            },
        },
        "handlers": handlers,
        "root": {
            "level": level,
            "handlers": ["default", "file"],
        },
        "loggers": loggers,
    }


def configure_logging(process_name: str) -> dict[str, object]:
    """Configure the root logger using env-var defaults.

    Runs at process import time, before database access is available, so it
    can only use settings.* (env-var backed) values. process_name distinguishes
    the log file per process (e.g. "app", "worker") so both can share
    settings.log_directory without clobbering each other.

    Once the database is reachable, callers should follow up with
    reconfigure_logging() to layer in persisted overrides from the
    Settings / Logging page.
    """
    log_config = _build_log_config(
        process_name,
        default_level=settings.log_level,
        workflow_log_enabled=True,
        workflow_log_level=settings.log_level,
        workflow_log_max_bytes=settings.log_max_bytes,
        workflow_log_backup_count=settings.log_backup_count,
        muted_loggers=DEFAULT_MUTED_LOGGERS,
    )
    logging.config.dictConfig(log_config)
    return log_config


def reconfigure_logging(
    process_name: str,
    *,
    default_level: str,
    workflow_log_enabled: bool,
    workflow_log_level: str,
    workflow_log_max_bytes: int,
    workflow_log_backup_count: int,
    muted_loggers: dict[str, str],
) -> dict[str, object]:
    """Re-apply logging config from persisted Settings / Logging overrides.

    Safe to call multiple times; each call fully replaces the previous
    dictConfig for this process.
    """
    log_config = _build_log_config(
        process_name,
        default_level=default_level,
        workflow_log_enabled=workflow_log_enabled,
        workflow_log_level=workflow_log_level,
        workflow_log_max_bytes=workflow_log_max_bytes,
        workflow_log_backup_count=workflow_log_backup_count,
        muted_loggers=muted_loggers,
    )
    logging.config.dictConfig(log_config)
    return log_config
