"""Pydantic models for Settings-based Git source operations."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator


class GitSourceTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test stored credentials."""

    url: str | None = Field(default=None, min_length=1)
    branch: str = Field(default="main", min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    token: str = Field(default="", max_length=2048)
    verify_ssl: bool = True
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_url(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_url = bool((self.url or "").strip())
        if has_source == has_url:
            raise ValueError("Provide either source_id or url")
        return self


class GitSourceTestConnectionResponse(BaseModel):
    success: bool
    message: str
