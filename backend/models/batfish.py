"""Pydantic models for Batfish source configuration."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class BatfishSourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=9996, ge=1, le=65535)


class BatfishSourceUpdateRequest(BaseModel):
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)


class BatfishTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test a stored source."""

    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int = Field(default=9996, ge=1, le=65535)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_inline(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_inline = bool((self.host or "").strip())
        if has_source == has_inline:
            raise ValueError("Provide either source_id or host")
        return self


class BatfishSourceResponse(BaseModel):
    source_id: str
    host: str
    port: int


class BatfishSourceListResponse(BaseModel):
    sources: list[BatfishSourceResponse]
    total: int


class BatfishTestConnectionResponse(BaseModel):
    success: bool
    message: str
