from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from models.hatchet import (
    HatchetSettingsResponse,
    HatchetSettingsUpdate,
    HatchetStatusResponse,
)
from services.hatchet.hatchet_settings_service import HatchetSettingsService

router = APIRouter(
    prefix="/hatchet",
    tags=["hatchet"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> HatchetSettingsService:
    return HatchetSettingsService(db)


@router.get("/settings", response_model=HatchetSettingsResponse)
async def get_hatchet_settings(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetSettingsResponse:
    return service.get_settings()


@router.put("/settings", response_model=HatchetSettingsResponse)
async def update_hatchet_settings(
    body: HatchetSettingsUpdate,
    service: HatchetSettingsService = Depends(_service),
) -> HatchetSettingsResponse:
    return service.update_settings(body)


@router.post("/test", response_model=HatchetStatusResponse)
async def test_hatchet_connection(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetStatusResponse:
    return await service.get_status()
