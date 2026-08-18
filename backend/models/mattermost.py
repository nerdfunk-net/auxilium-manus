"""Pydantic models for Mattermost source configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class MattermostSourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    url: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)


class MattermostSourceUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1)
    token: str | None = Field(default=None, min_length=1)
    verify_ssl: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=120)


class MattermostSourceResponse(BaseModel):
    source_id: str
    url: str
    verify_ssl: bool
    timeout: float


class MattermostSourceListResponse(BaseModel):
    sources: list[MattermostSourceResponse]
    total: int


class MattermostTestConnectionResponse(BaseModel):
    success: bool
    message: str
