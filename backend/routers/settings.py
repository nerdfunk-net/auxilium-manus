from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from services.settings.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> SettingsService:
    return SettingsService(db)


@router.get("", response_model=SettingListResponse)
async def list_settings(
    key_prefix: str | None = Query(None, max_length=255),
    _current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(_service),
) -> SettingListResponse:
    return service.list_settings(key_prefix=key_prefix)


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    _current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(_service),
) -> SettingResponse:
    return service.get_setting(key)


@router.post("", response_model=SettingResponse, status_code=status.HTTP_201_CREATED)
async def create_setting(
    body: SettingCreate,
    _current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(_service),
) -> SettingResponse:
    return service.create_setting(body)


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    body: SettingUpdate,
    _current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(_service),
) -> SettingResponse:
    return service.update_setting(key, body)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting(
    key: str,
    _current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(_service),
) -> None:
    service.delete_setting(key)
