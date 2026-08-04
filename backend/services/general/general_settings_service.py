"""Business logic for application general configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from core.config import PROJECT_ROOT
from core.config import settings as app_settings
from models.general_settings import GeneralSettings, GeneralSettingsResponse
from repositories.settings_repository import SettingsRepository

SETTINGS_KEY = "general.config"


def _resolve_export_directory(value: str) -> Path:
    if not value:
        return app_settings.data_directory
    # Anchor relative paths to the project root rather than the current
    # working directory: this setting is read by the Hatchet worker process
    # (via the store-artifact step), which may be launched from a different
    # cwd than the API server that saved the value — cwd-relative resolution
    # would silently resolve to a different location in each process.
    return (PROJECT_ROOT / Path(value)).resolve()


def _to_response(cfg: GeneralSettings) -> GeneralSettingsResponse:
    return GeneralSettingsResponse(
        **cfg.model_dump(),
        resolved_export_directory=str(_resolve_export_directory(cfg.default_export_directory)),
    )


class GeneralSettingsService:
    def __init__(self, db: Session) -> None:
        self._repo = SettingsRepository(db)

    def _load(self) -> GeneralSettings:
        row = self._repo.get_by_key(SETTINGS_KEY)
        if row is None:
            return GeneralSettings()
        return GeneralSettings.model_validate(row.value)

    def get_settings(self) -> GeneralSettingsResponse:
        return _to_response(self._load())

    def update_settings(self, body: GeneralSettings) -> GeneralSettingsResponse:
        row = self._repo.get_by_key(SETTINGS_KEY)
        value: dict[str, Any] = body.model_dump()
        if row is None:
            self._repo.create(
                key=SETTINGS_KEY, value=value, description="Application general configuration"
            )
        else:
            self._repo.update(row, {"value": value})
        return _to_response(body)

    def resolved_export_directory(self) -> Path:
        return _resolve_export_directory(self._load().default_export_directory)
