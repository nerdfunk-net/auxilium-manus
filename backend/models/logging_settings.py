"""Pydantic models for application logging configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

DEFAULT_MUTED_LOGGERS: dict[str, str] = {
    "watchfiles": "WARNING",
    "netmiko": "WARNING",
    "paramiko": "WARNING",
    "paramiko.transport": "WARNING",
    "grpc": "WARNING",
    "grpc._cython.cygrpc": "WARNING",
    "hpack": "WARNING",
}


def _validate_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in VALID_LOG_LEVELS:
        raise ValueError(f"log level must be one of {VALID_LOG_LEVELS}")
    return normalized


class LoggingSettings(BaseModel):
    default_log_level: str = Field(default="INFO")
    workflow_log_enabled: bool = Field(default=True)
    workflow_log_level: str = Field(default="INFO")
    workflow_log_max_bytes: int = Field(default=10_485_760, ge=1_048_576, le=1_073_741_824)
    workflow_log_backup_count: int = Field(default=5, ge=0, le=50)
    muted_loggers: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MUTED_LOGGERS))

    @field_validator("default_log_level", "workflow_log_level")
    @classmethod
    def _validate_top_level(cls, value: str) -> str:
        return _validate_level(value)

    @field_validator("muted_loggers")
    @classmethod
    def _validate_muted_levels(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            name.strip(): _validate_level(level)
            for name, level in value.items()
            if name.strip()
        }


class LoggingSettingsResponse(LoggingSettings):
    log_directory: str
    app_log_file: str
    worker_log_file: str
    workflow_log_file: str
