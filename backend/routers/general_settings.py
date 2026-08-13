"""Router for application general configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from models.general_settings import GeneralSettings, GeneralSettingsResponse
from services.general.general_settings_service import GeneralSettingsService

router = APIRouter(
    prefix="/general",
    tags=["general"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> GeneralSettingsService:
    return GeneralSettingsService(db)


@router.get(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "read"))],
)
async def get_general_settings(
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "write"))],
)
async def update_general_settings(
    body: GeneralSettings,
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.update_settings(body)
