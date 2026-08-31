"""Pydantic models for Mattermost source configuration."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class MattermostSourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    url: str = Field(..., min_length=1)
    credential_id: int = Field(..., gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)


class MattermostSourceUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=120)


class MattermostTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test stored credentials."""

    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_inline(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_inline = bool((self.url or "").strip()) and self.credential_id is not None
        if has_source == has_inline:
            raise ValueError("Provide either source_id or both url and credential_id")
        return self


class MattermostSourceResponse(BaseModel):
    source_id: str
    url: str
    verify_ssl: bool
    timeout: float
    credential_id: int | None = None
    credential_name: str | None = None


class MattermostSourceListResponse(BaseModel):
    sources: list[MattermostSourceResponse]
    total: int


class MattermostTestConnectionResponse(BaseModel):
    success: bool
    message: str
