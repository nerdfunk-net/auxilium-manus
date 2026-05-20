from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SettingCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9._-]+$")
    value: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(None, max_length=2000)


class SettingUpdate(BaseModel):
    value: dict[str, Any] | None = None
    description: str | None = Field(None, max_length=2000)


class SettingResponse(BaseModel):
    id: int
    key: str
    value: dict[str, Any]
    description: str | None
    created_at: datetime
    updated_at: datetime


class SettingListResponse(BaseModel):
    settings: list[SettingResponse]
    total: int
