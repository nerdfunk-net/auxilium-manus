"""Router for application logging configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from models.logging_settings import LoggingSettings, LoggingSettingsResponse
from services.logging.logging_settings_service import LoggingSettingsService

router = APIRouter(
    prefix="/logging",
    tags=["logging"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> LoggingSettingsService:
    return LoggingSettingsService(db)


@router.get(
    "/settings",
    response_model=LoggingSettingsResponse,
    dependencies=[Depends(require_permission("logging_settings", "read"))],
)
async def get_logging_settings(
    service: LoggingSettingsService = Depends(_service),
) -> LoggingSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=LoggingSettingsResponse,
    dependencies=[Depends(require_permission("logging_settings", "write"))],
)
async def update_logging_settings(
    body: LoggingSettings,
    service: LoggingSettingsService = Depends(_service),
) -> LoggingSettingsResponse:
    result = service.update_settings(body)
    service.apply_to_current_process("app")
    return result
