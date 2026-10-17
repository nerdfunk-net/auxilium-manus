from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import get_current_user, require_permission
from models.hatchet import HatchetConfigResponse, HatchetStatusResponse
from services.hatchet.hatchet_settings_service import HatchetSettingsService

router = APIRouter(
    prefix="/hatchet",
    tags=["hatchet"],
    dependencies=[Depends(get_current_user)],
)


def _service() -> HatchetSettingsService:
    return HatchetSettingsService()


@router.get(
    "/settings",
    response_model=HatchetConfigResponse,
    dependencies=[Depends(require_permission("hatchet_settings", "read"))],
)
def get_hatchet_settings(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetConfigResponse:
    return service.get_config()


@router.post(
    "/test",
    response_model=HatchetStatusResponse,
    dependencies=[Depends(require_permission("hatchet_settings", "read"))],
)
async def test_hatchet_connection(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetStatusResponse:
    return await service.check_connection()
