"""Router for Redis cache settings and management."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import service_factory
from core.auth import get_current_user, require_permission
from core.database import get_db
from models.cache_settings import (
    CacheClearResponse,
    CacheSettings,
    CacheSettingsResponse,
    CacheStatsResponse,
)
from services.cache.cache_settings_service import CacheSettingsService

router = APIRouter(
    prefix="/cache",
    tags=["cache"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> CacheSettingsService:
    return CacheSettingsService(db, service_factory.build_cache_service())


@router.get(
    "/settings",
    response_model=CacheSettingsResponse,
    dependencies=[Depends(require_permission("cache_settings", "read"))],
)
async def get_cache_settings(
    service: CacheSettingsService = Depends(_service),
) -> CacheSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=CacheSettingsResponse,
    dependencies=[Depends(require_permission("cache_settings", "write"))],
)
async def update_cache_settings(
    body: CacheSettings,
    service: CacheSettingsService = Depends(_service),
) -> CacheSettingsResponse:
    return service.update_settings(body)


@router.get(
    "/stats",
    response_model=CacheStatsResponse,
    dependencies=[Depends(require_permission("cache_settings", "read"))],
)
async def get_cache_stats(
    service: CacheSettingsService = Depends(_service),
) -> CacheStatsResponse:
    return service.get_stats()


@router.post(
    "/clear",
    response_model=CacheClearResponse,
    dependencies=[Depends(require_permission("cache_settings", "write"))],
)
async def clear_cache(
    service: CacheSettingsService = Depends(_service),
) -> CacheClearResponse:
    return service.clear()
