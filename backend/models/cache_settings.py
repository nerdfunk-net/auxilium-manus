"""Pydantic models for Redis cache settings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CacheSettings(BaseModel):
    enabled: bool = True
    device_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    # Per-filter cache of the Nautobot location query (see live_query_mixin).
    location_ttl_seconds: int = Field(default=600, ge=60, le=86400)


class CacheSettingsResponse(CacheSettings):
    redis_connected: bool


class CacheStatsResponse(BaseModel):
    connected: bool
    overview: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    namespaces: dict[str, Any] = {}


class CacheClearResponse(BaseModel):
    cleared: int


class CacheRebuildResponse(BaseModel):
    """A rebuild runs in the background on the Hatchet worker; this only confirms it started."""

    started: bool
    hatchet_run_id: str
