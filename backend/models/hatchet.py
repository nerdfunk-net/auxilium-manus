from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HatchetSettingsResponse(BaseModel):
    host_port: str
    dashboard_url: str
    debug: bool
    worker_name: str
    worker_slots: int
    token_configured: bool


class HatchetSettingsUpdate(BaseModel):
    host_port: str | None = Field(None, min_length=1, max_length=255)
    token: str | None = Field(None, max_length=4096)
    dashboard_url: str | None = Field(None, max_length=512)
    debug: bool | None = None
    worker_name: str | None = Field(None, min_length=1, max_length=255)
    worker_slots: int | None = Field(None, ge=1, le=100)


class HatchetStatusResponse(BaseModel):
    reachable: bool
    token_configured: bool
    host_port: str
    dashboard_url: str
    message: str
    checked_at: datetime
