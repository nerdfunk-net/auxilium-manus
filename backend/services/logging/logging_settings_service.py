"""Business logic for application logging configuration."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings as app_settings
from core.logging_config import reconfigure_logging
from models.logging_settings import LoggingSettings, LoggingSettingsResponse
from repositories.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)

SETTINGS_KEY = "logging.config"
_DEFAULTS = LoggingSettings()


def _to_response(cfg: LoggingSettings) -> LoggingSettingsResponse:
    return LoggingSettingsResponse(
        **cfg.model_dump(),
        log_directory=str(app_settings.log_directory),
        app_log_file=str(app_settings.log_directory / "app.log"),
        worker_log_file=str(app_settings.log_directory / "worker.log"),
        workflow_log_file=str(app_settings.log_directory / "workflow.log"),
    )


class LoggingSettingsService:
    def __init__(self, db: Session) -> None:
        self._repo = SettingsRepository(db)

    def _load(self) -> LoggingSettings:
        row = self._repo.get_by_key(SETTINGS_KEY)
        if row is None:
            return _DEFAULTS
        return LoggingSettings.model_validate(row.value)

    def get_settings(self) -> LoggingSettingsResponse:
        return _to_response(self._load())

    def update_settings(self, body: LoggingSettings) -> LoggingSettingsResponse:
        row = self._repo.get_by_key(SETTINGS_KEY)
        value: dict[str, Any] = body.model_dump()
        if row is None:
            self._repo.create(
                key=SETTINGS_KEY, value=value, description="Application logging configuration"
            )
        else:
            self._repo.update(row, {"value": value})
        return _to_response(body)

    def apply_to_current_process(self, process_name: str) -> None:
        """Re-apply the persisted logging config to *this* process immediately.

        Called at startup (after the DB is reachable) and right after a save,
        so the process handling the request picks up changes without a
        restart. Other processes (e.g. the Hatchet worker, when this is
        called from the API server) only pick up the change on their next
        restart — same tradeoff as Hatchet client settings.
        """
        cfg = self._load()
        reconfigure_logging(
            process_name,
            default_level=cfg.default_log_level,
            workflow_log_enabled=cfg.workflow_log_enabled,
            workflow_log_level=cfg.workflow_log_level,
            workflow_log_max_bytes=cfg.workflow_log_max_bytes,
            workflow_log_backup_count=cfg.workflow_log_backup_count,
            muted_loggers=cfg.muted_loggers,
        )
        logger.info("Applied logging configuration to process=%s", process_name)
