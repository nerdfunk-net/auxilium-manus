"""Pydantic models for Settings-based Git source operations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitSourceTestConnectionRequest(BaseModel):
    """Credentials from the Settings / Sources form (not necessarily saved yet)."""

    url: str = Field(..., min_length=1)
    branch: str = Field(default="main", min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    token: str = Field(default="", max_length=2048)
    verify_ssl: bool = True


class GitSourceTestConnectionResponse(BaseModel):
    success: bool
    message: str
