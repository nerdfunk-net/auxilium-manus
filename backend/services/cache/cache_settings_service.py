"""Business logic for Redis cache settings."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models.cache_settings import (
    CacheClearResponse,
    CacheSettings,
    CacheSettingsResponse,
    CacheStatsResponse,
)
from repositories.settings_repository import SettingsRepository
from services.cache.redis_cache_service import RedisCacheService

logger = logging.getLogger(__name__)

SETTINGS_KEY = "cache.redis"
_DEFAULTS = CacheSettings()


class CacheSettingsService:
    def __init__(
        self,
        db: Session,
        cache_service: RedisCacheService | None,
    ) -> None:
        self._repo = SettingsRepository(db)
        self._cache = cache_service

    def _load(self) -> CacheSettings:
        row = self._repo.get_by_key(SETTINGS_KEY)
        if row is None:
            return _DEFAULTS
        return CacheSettings.model_validate(row.value)

    def get_settings(self) -> CacheSettingsResponse:
        cfg = self._load()
        return CacheSettingsResponse(
            enabled=cfg.enabled,
            device_ttl_seconds=cfg.device_ttl_seconds,
            redis_connected=self._cache is not None,
        )

    def update_settings(self, body: CacheSettings) -> CacheSettingsResponse:
        row = self._repo.get_by_key(SETTINGS_KEY)
        value = body.model_dump()
        if row is None:
            self._repo.create(
                key=SETTINGS_KEY, value=value, description="Redis cache configuration"
            )
        else:
            self._repo.update(row, {"value": value})
        return CacheSettingsResponse(
            enabled=body.enabled,
            device_ttl_seconds=body.device_ttl_seconds,
            redis_connected=self._cache is not None,
        )

    def get_stats(self) -> CacheStatsResponse:
        if self._cache is None:
            return CacheStatsResponse(connected=False)
        try:
            data = self._cache.stats()
            return CacheStatsResponse(
                connected=True,
                overview=data.get("overview", {}),
                performance=data.get("performance", {}),
                namespaces=data.get("namespaces", {}),
            )
        except Exception as exc:
            logger.error("Failed to fetch cache stats: %s", exc)
            return CacheStatsResponse(connected=False)

    def clear(self) -> CacheClearResponse:
        if self._cache is None:
            return CacheClearResponse(cleared=0)
        try:
            count = self._cache.clear_all()
            logger.info("Cache cleared: %d keys removed", count)
            return CacheClearResponse(cleared=count)
        except Exception as exc:
            logger.error("Failed to clear cache: %s", exc)
            return CacheClearResponse(cleared=0)
