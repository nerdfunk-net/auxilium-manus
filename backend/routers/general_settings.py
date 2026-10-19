"""Router for application general configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from models.general_settings import (
    ClientSettingsResponse,
    GeneralSettings,
    GeneralSettingsResponse,
)
from services.general.general_settings_service import GeneralSettingsService

router = APIRouter(
    prefix="/general",
    tags=["general"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> GeneralSettingsService:
    return GeneralSettingsService(db)


@router.get("/client-settings", response_model=ClientSettingsResponse)
def get_client_settings(
    service: GeneralSettingsService = Depends(_service),
) -> ClientSettingsResponse:
    # Any signed-in user: the idle-logout timeout applies to every session, so it cannot sit
    # behind general_settings:read (non-admins would silently fall back to the built-in default).
    settings = service.get_settings()
    return ClientSettingsResponse(
        session_timeout_minutes=settings.session_timeout_minutes,
        switch_to_runs_on_start=settings.switch_to_runs_on_start,
    )


@router.get(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "read"))],
)
def get_general_settings(
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "write"))],
)
def update_general_settings(
    body: GeneralSettings,
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.update_settings(body)
