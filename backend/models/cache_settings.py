"""Pydantic models for Redis cache settings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CacheSettings(BaseModel):
    enabled: bool = True
    device_ttl_seconds: int = Field(default=1800, ge=60, le=86400)


class CacheSettingsResponse(CacheSettings):
    redis_connected: bool


class CacheStatsResponse(BaseModel):
    connected: bool
    overview: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    namespaces: dict[str, Any] = {}


class CacheClearResponse(BaseModel):
    cleared: int
