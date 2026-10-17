"""Pydantic models for application general configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class GeneralSettings(BaseModel):
    session_timeout_minutes: int = Field(default=20, ge=1, le=1440)
    default_export_directory: str = Field(default="")
    switch_to_runs_on_start: bool = Field(default=True)

    @field_validator("default_export_directory")
    @classmethod
    def _strip_export_directory(cls, value: str) -> str:
        return value.strip()


class GeneralSettingsResponse(GeneralSettings):
    resolved_export_directory: str
